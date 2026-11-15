"""Live status of a running phone: CPU (and each core), GPU, memory, battery, every temperature
sensor, network, and a task-manager style process list.

Read-only. Each sample is a few `cat` reads of /proc and /sys plus `dumpsys battery`, done
in one adb round trip. Rates (CPU %, network speed) come from the change since the previous
sample, so the first sample has none. Anything the phone does not allow reading is None and
the screen simply leaves that value out.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Tuple

_MARK = "@@m@@"

_COMMANDS = [
    "grep '^cpu' /proc/stat",
    "grep -E '^(MemTotal|MemAvailable|SwapTotal|SwapFree):' /proc/meminfo",
    "dumpsys battery",
    "cat /sys/class/power_supply/battery/current_now",
    "cat /proc/net/dev",
    "cat /sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq",
    "for z in /sys/class/thermal/thermal_zone*; do echo \"$(cat $z/type) $(cat $z/temp)\"; done",
    "df -k /data | tail -n 1",
    "cat /sys/devices/system/cpu/cpu[0-9]*/cpufreq/cpuinfo_max_freq",
    "cat /sys/class/kgsl/kgsl-3d0/gpu_busy_percentage",
    "cat /sys/class/kgsl/kgsl-3d0/gpuclk",
    "cat /sys/class/kgsl/kgsl-3d0/max_gpuclk",
    "cat /sys/class/misc/mali0/device/utilisation /sys/class/misc/mali0/device/gpu_utilization",
    "for d in /sys/class/devfreq/*; do echo \"$(basename $d) $(cat $d/cur_freq) $(cat $d/max_freq)\"; done",
]
SAMPLE_COMMAND = "; ".join(f"echo {_MARK}; {c} 2>/dev/null" for c in _COMMANDS)
TOP_COMMAND = "top -b -n 1 -m 120 2>/dev/null"


# ------------------------------------------------------------------ parsing
def parse_cpu_stat(line: str) -> Optional[Tuple[int, int]]:
    """(busy, total) jiffies from the first line of /proc/stat."""
    nums = re.findall(r"\d+", line.split("cpu", 1)[-1]) if line.strip().startswith("cpu") else []
    if len(nums) < 4:
        return None
    values = [int(n) for n in nums[:8]]
    idle = values[3] + (values[4] if len(values) > 4 else 0)  # idle + iowait
    total = sum(values)
    return total - idle, total


def parse_cpu_cores(text: str) -> Dict[str, Tuple[int, int]]:
    """{"cpu": (busy, total), "cpu0": ..., "cpu1": ...} from every cpu line of /proc/stat."""
    out: Dict[str, Tuple[int, int]] = {}
    for line in text.splitlines():
        name = line.split(None, 1)[0] if line.strip() else ""
        if re.fullmatch(r"cpu\d*", name):
            parsed = parse_cpu_stat(line)
            if parsed:
                out[name] = parsed
    return out


def parse_meminfo(text: str) -> Dict[str, int]:
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"^(\w+):\s+(\d+)\s*kB", text, re.M)}


def parse_net(text: str) -> Optional[Tuple[int, int]]:
    """(bytes received, bytes sent) over every interface except loopback."""
    rx = tx = 0
    seen = False
    for line in text.splitlines():
        if ":" not in line:
            continue
        name, data = line.split(":", 1)
        name, cols = name.strip(), data.split()
        if name in ("lo", "dummy0") or len(cols) < 9 or not cols[0].isdigit():
            continue
        rx, tx, seen = rx + int(cols[0]), tx + int(cols[8]), True
    return (rx, tx) if seen else None


def parse_freqs(text: str) -> List[int]:
    """CPU core speeds in MHz."""
    return [int(n) // 1000 for n in re.findall(r"^\d+$", text, re.M) if int(n) > 0]


def parse_thermal(text: str) -> List[Tuple[str, float]]:
    """(sensor name, degrees C). Values come as millidegrees (or degrees on some phones)."""
    out: List[Tuple[str, float]] = []
    for line in text.splitlines():
        m = re.match(r"^(\S+)\s+(-?\d+)$", line.strip())
        if not m:
            continue
        value = int(m.group(2))
        degrees = value / 1000 if abs(value) >= 1000 else float(value)
        if 0 < degrees < 130:
            out.append((m.group(1), degrees))
    return out


_PARTS = (("cpu_temp", re.compile(r"^cpu", re.I)),                       # cpu-0-0-usr, cpuss-0-usr, cpu_thermal
          ("gpu_temp", re.compile(r"^(gpu|mali|kgsl)", re.I)),            # gpuss-0-usr, gpu-thermal
          ("ram_temp", re.compile(r"^(ddr|dram|lpddr|mem)", re.I)))       # ddr-0-usr, dram
_VIRTUAL = re.compile(r"(step|lvl|lowf|limit)", re.I)                     # thermal limiters, not measurements


def soc_temps(sensors: List[Tuple[str, float]]) -> Dict[str, float]:
    """The temperature of the chip's parts, from the phone's sensors: {"cpu_temp", "gpu_temp", "ram_temp"} in degrees
    C, each the hottest sensor of that part. A part the phone has no sensor for is left out."""
    out: Dict[str, float] = {}
    for key, pattern in _PARTS:
        values = [round(d, 1) for n, d in sensors if pattern.match(n) and not _VIRTUAL.search(n)]
        if values:
            out[key] = max(values)
    return out


def parse_battery(text: str) -> Dict[str, object]:
    kv = dict(re.findall(r"^\s*([A-Za-z ]+):\s*(\S.*)$", text, re.M))

    def num(key):
        v = kv.get(key, "").strip()
        return int(v) if re.fullmatch(r"-?\d+", v) else None

    status = {"2": "Charging", "3": "Discharging", "4": "Not charging", "5": "Full"}.get(kv.get("status", "").strip(), "")
    temp = num("temperature")
    return {"level": num("level"), "voltage_mv": num("voltage"), "temp_c": None if temp is None else temp / 10,
            "status": status, "technology": kv.get("technology", "").strip() or None}


def parse_size_mb(text: str) -> Optional[float]:
    """"200M", "1.2G", "512K" or a plain number of KiB, as megabytes."""
    m = re.fullmatch(r"([\d.]+)\s*([KMGT]?)", text.strip(), re.I)
    if not m:
        return None
    value = float(m.group(1))
    unit = m.group(2).upper() or "K"
    return value * {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1048576}[unit]


def classify_process(user: str, name: str) -> str:
    """"kernel" (kworker, ksoftirqd...), "app" (an installed app's own user u0_aNNN) or "system"."""
    if name.startswith("[") or re.fullmatch(r"k\w+/\d+.*|kthreadd|migration/\d+|rcu_\w+|irq/.*", name):
        return "kernel"
    return "app" if re.fullmatch(r"u\d+_a\d+|u\d+_i\d+", user) else "system"


def parse_processes(text: str) -> Tuple[List[Dict[str, object]], Optional[int]]:
    """Every process from `top -b -n 1`: (rows, total count). Row keys: pid, user, state, cpu (%),
    mem_mb, mem_pct, time, name, kind."""
    total = None
    m = re.search(r"Tasks:\s*(\d+)\s*total", text)
    if m:
        total = int(m.group(1))
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "PID" in line and ("ARGS" in line or "COMMAND" in line):
            header = line.replace("S[%CPU]", "S %CPU").split()
            col = {h.strip("[]"): j for j, h in enumerate(header)}
            if "%CPU" not in col or "PID" not in col:
                return [], total
            rows: List[Dict[str, object]] = []
            for row in lines[i + 1:]:
                cols = row.split(None, len(header) - 1)
                if len(cols) < len(header):
                    continue
                try:
                    cpu = float(cols[col["%CPU"]])
                    pid = int(cols[col["PID"]])
                except ValueError:
                    continue
                name = cols[-1].strip().split()[0]
                if name.startswith("top") or name in ("sh", "toybox"):
                    continue  # our own reading
                user = cols[col["USER"]] if "USER" in col else ""
                try:
                    mem_pct = float(cols[col["%MEM"]]) if "%MEM" in col else None
                except ValueError:
                    mem_pct = None
                rows.append({"pid": pid, "user": user, "state": cols[col["S"]] if "S" in col else "",
                             "cpu": cpu, "mem_mb": parse_size_mb(cols[col["RES"]]) if "RES" in col else None,
                             "mem_pct": mem_pct, "time": cols[col["TIME+"]] if "TIME+" in col else "",
                             "name": name, "kind": classify_process(user, name)})
            return rows, total
    return [], total


def parse_gpu(busy: str, clk: str, max_clk: str, mali: str, devfreq: str) -> Dict[str, object]:
    """GPU load and speed from Qualcomm Adreno (kgsl), Arm Mali or a devfreq node named gpu."""
    out: Dict[str, object] = {}
    m = re.match(r"\s*(\d+)", busy)
    if m:
        out["gpu_pct"] = min(100, int(m.group(1)))
    if clk.strip().isdigit():
        out["gpu_mhz"] = int(clk) // 1_000_000
    if max_clk.strip().isdigit():
        out["gpu_max_mhz"] = int(max_clk) // 1_000_000
    m = re.search(r"(\d+)", mali)
    if m and "gpu_pct" not in out and int(m.group(1)) <= 100:
        out["gpu_pct"] = int(m.group(1))
    for line in devfreq.splitlines():
        parts = line.split()
        if (len(parts) >= 3 and re.search(r"gpu|kgsl|mali", parts[0], re.I) and parts[1].isdigit()
                and not re.search(r"bw|llcc|ddr|bus", parts[0], re.I)  # bandwidth and cache nodes, not the GPU clock
                and int(parts[1]) >= 1_000_000):
            if "gpu_mhz" not in out:
                out["gpu_mhz"] = int(parts[1]) // 1_000_000
            if "gpu_max_mhz" not in out and parts[2].isdigit():
                out["gpu_max_mhz"] = int(parts[2]) // 1_000_000
    return out


def parse_top(text: str, limit: int = 5) -> List[Tuple[str, float]]:
    """The busiest processes as (name, CPU %), from toybox/procps `top -b -n 1`."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "PID" in line and "ARGS" in line or ("PID" in line and "COMMAND" in line):
            header = line.replace("S[%CPU]", "S %CPU").split()
            cpu = next((j for j, h in enumerate(header) if h in ("%CPU", "[%CPU]")), None)
            if cpu is None:
                return []
            out: List[Tuple[str, float]] = []
            for row in lines[i + 1:]:
                cols = row.split(None, len(header) - 1)
                if len(cols) < len(header):
                    continue
                try:
                    value = float(cols[cpu])
                except ValueError:
                    continue
                name = cols[-1].strip().split()[0]
                if name.startswith(("top", "[")) or name in ("sh", "toybox"):
                    continue  # our own reading, and kernel threads ("[kworker/0:1]") which are not apps
                out.append((name, value))
            out.sort(key=lambda x: -x[1])
            return [x for x in out if x[1] > 0][:limit]
    return []


# --------------------------------------------------------------------- sampling
class Monitor:
    """Takes samples from one phone. `phone` needs a shell(command) -> str method."""

    def __init__(self, phone):
        self.phone = phone
        self._cpu: Dict[str, Tuple[int, int]] = {}
        self._net: Optional[Tuple[int, int, float]] = None
        self._count = 0

    def sample(self) -> Dict[str, object]:
        now = time.monotonic()
        raw = self.phone.shell(SAMPLE_COMMAND, 20000)
        parts = [p.strip() for p in raw.split(_MARK)[1:]]
        parts += [""] * (len(_COMMANDS) - len(parts))
        stat, mem, battery, current, net, freqs, thermal, storage, max_freqs = parts[:9]
        gpu_busy, gpu_clk, gpu_max, mali, devfreq = parts[9:14]
        out: Dict[str, object] = {"time": time.time()}

        # Each reading is parsed on its own: a phone that answers one of them oddly loses that
        # value for a second, never the whole sample.
        def cpu_step() -> None:
            cpus = parse_cpu_cores(stat)
            rates = {}
            for name, (busy, total) in cpus.items():
                before = self._cpu.get(name)
                if before and total > before[1]:
                    rates[name] = round(100 * (busy - before[0]) / (total - before[1]), 1)
            if "cpu" in rates:
                out["cpu"] = rates["cpu"]
            cores = sorted((int(n[3:]), v) for n, v in rates.items() if n != "cpu")
            if cores:
                out["core_pct"] = [v for _i, v in cores]
            self._cpu = cpus or self._cpu

        def gpu_step() -> None:
            out.update(parse_gpu(gpu_busy, gpu_clk, gpu_max, mali, devfreq))

        def memory_step() -> None:
            info = parse_meminfo(mem)
            if info.get("MemTotal") and "MemAvailable" in info:
                used = info["MemTotal"] - info["MemAvailable"]
                out.update(mem_pct=round(100 * used / info["MemTotal"], 1), mem_used_gb=round(used / 1048576, 2),
                           mem_total_gb=round(info["MemTotal"] / 1048576, 2))
            if info.get("SwapTotal"):
                out["swap_used_mb"] = round((info["SwapTotal"] - info.get("SwapFree", 0)) / 1024)

        def battery_step() -> None:
            out.update({f"battery_{k}": v for k, v in parse_battery(battery).items()})
            if re.fullmatch(r"-?\d+", current):
                ua = int(current)
                out["current_ma"] = round(ua / 1000 if abs(ua) > 20000 else ua)  # µA on most phones, mA on some

        def network_step() -> None:
            counters = parse_net(net)
            if counters and self._net and now > self._net[2]:
                dt = now - self._net[2]
                out["net_down_kbs"] = round(max(0, counters[0] - self._net[0]) / 1024 / dt, 1)
                out["net_up_kbs"] = round(max(0, counters[1] - self._net[1]) / 1024 / dt, 1)
            self._net = (counters + (now,)) if counters else self._net

        def speed_step() -> None:
            speeds = parse_freqs(freqs)
            if speeds:
                out["cpu_mhz"] = max(speeds)
                out["cores_mhz"] = speeds
                out["cores_max_mhz"] = parse_freqs(max_freqs)

        def storage_step() -> None:
            cols = storage.split()
            if len(cols) >= 4 and cols[1].isdigit() and cols[2].isdigit():
                out["storage_total_gb"] = round(int(cols[1]) / 1048576, 1)
                out["storage_used_gb"] = round(int(cols[2]) / 1048576, 1)

        def sensor_step() -> None:
            sensors = parse_thermal(thermal)
            if sensors:
                name, degrees = max(sensors, key=lambda s: s[1])
                out["hottest"] = (name, round(degrees, 1))
                out["thermal"] = sorted(((n, round(d, 1)) for n, d in sensors), key=lambda s: -s[1])
                out.update(soc_temps(sensors))

        for step in (cpu_step, gpu_step, memory_step, battery_step, network_step, speed_step, storage_step, sensor_step):
            try:
                step()
            except Exception:  # one odd reading must not cost the others
                pass

        if self._count % 2 == 0:  # the process list: `top` is the slow part, so every other reading
            try:
                rows, total = parse_processes(self.phone.shell(TOP_COMMAND, 20000))
                out["procs"], out["proc_total"] = rows, total
                out["top"] = [(r["name"], r["cpu"]) for r in rows if r["kind"] != "kernel" and r["cpu"] > 0][:5]
            except Exception:
                out["procs"], out["top"] = [], []
        self._count += 1
        return out
