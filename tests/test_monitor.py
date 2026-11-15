"""Live status: parsing the phone's /proc and /sys readings, and rates between samples."""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mitoolkit import monitor  # noqa: E402
from mitoolkit.ui.components.charts import nice_ceiling  # noqa: E402

TOP = """Tasks: 500 total,   1 running, 499 sleeping
800%cpu  42%user   0%nice  18%sys 735%idle
  PID USER         PR  NI VIRT  RES  SHR S[%CPU] %MEM     TIME+ ARGS
 4242 u0_a123      20   0  14G 200M 100M S  35.5   3.1   0:01.23 com.example.video
 1000 system       18  -2  12G 300M 120M S  12.0   5.0   9:01.00 system_server
 9999 shell        20   0 100M   5M   3M R   9.0   0.1   0:00.01 top -b -n 1
  100 root         20   0     0    0    0 S   0.0   0.0   0:00.00 kworker/0:1
"""


class ParseTests(unittest.TestCase):
    def test_cpu_stat(self):
        self.assertEqual(monitor.parse_cpu_stat("cpu  100 0 50 800 50 0 0 0"), (150, 1000))
        self.assertIsNone(monitor.parse_cpu_stat("nonsense"))

    def test_meminfo(self):
        info = monitor.parse_meminfo("MemTotal:        5600000 kB\nMemAvailable:    2000000 kB\nSwapTotal: 100 kB\n")
        self.assertEqual(info["MemTotal"], 5600000)
        self.assertEqual(info["MemAvailable"], 2000000)

    def test_net_skips_loopback(self):
        text = ("Inter-|   Receive\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets ...\n"
                "    lo: 999 1 0 0 0 0 0 0 999 1 0 0 0 0 0 0\n"
                " wlan0: 2048 10 0 0 0 0 0 0 1024 5 0 0 0 0 0 0\n"
                "rmnet_data0: 100 1 0 0 0 0 0 0 50 1 0 0 0 0 0 0\n")
        self.assertEqual(monitor.parse_net(text), (2148, 1074))

    def test_freqs_and_thermal(self):
        self.assertEqual(monitor.parse_freqs("1804800\n1056000\n"), [1804, 1056])
        sensors = monitor.parse_thermal("cpu-0-0 45000\nbattery 33200\nbroken\nbad 0\n")
        self.assertEqual(sensors, [("cpu-0-0", 45.0), ("battery", 33.2)])

    def test_battery(self):
        b = monitor.parse_battery("  level: 66\n  voltage: 4012\n  temperature: 332\n  status: 2\n")
        self.assertEqual((b["level"], b["voltage_mv"], b["temp_c"], b["status"]), (66, 4012, 33.2, "Charging"))

    def test_top(self):
        rows = monitor.parse_top(TOP)
        self.assertEqual(rows[0], ("com.example.video", 35.5))
        self.assertEqual(rows[1][0], "system_server")
        self.assertNotIn("top", [n for n, _ in rows])      # our own reading is left out
        self.assertEqual(len(rows), 2)                      # idle ones are left out
        self.assertEqual(monitor.parse_top("no table here"), [])

    def test_axis_ceiling(self):
        self.assertEqual(nice_ceiling(0), 1.0)
        self.assertEqual(nice_ceiling(3.2), 3.2)
        self.assertEqual(nice_ceiling(87), 100)
        self.assertEqual(nice_ceiling(0.07), 0.08)

    def test_without_a_baseline_the_first_sample_just_has_no_load(self):
        class NoStat(FakePhone):
            def shell(self, command, timeout_ms=0):
                if command == "cat /proc/stat":
                    raise OSError("not readable")
                return super().shell(command, timeout_ms)
        mon = monitor.Monitor(NoStat())
        self.assertNotIn("cpu", mon.sample())
        time.sleep(0.05)
        self.assertIn("cpu", mon.sample())                   # and the second one does, as before

    def test_zones_that_are_not_temperatures_are_left_out(self):
        """A Snapdragon phone lists battery voltage and current limits beside the temperatures: 3737 (mV) is not 3.7 C."""
        text = ("pm6150-vbat-lvl0 3737\npm6150-ibat-lvl0 703\npm6150l-bcl-lvl1 0\npm6150l-vph-lvl2 12\nsoc 60\n"
                "pm6150-bcl-lvl2 25\nbattery 38000\nbms 38000\ncpu-0-0-usr 48500\ngpuss-0-usr 45900\nconn-therm-usr -40000\n"
                "cpu-0-max-step 50400\ncpu-1-1-step 48800\naoss-0-lowf 48800\n")
        self.assertEqual([n for n, _d in monitor.parse_thermal(text)], ["battery", "bms", "cpu-0-0-usr", "gpuss-0-usr"])

    def test_the_battery_charge_is_never_the_hottest_sensor(self):
        """A phone with a zone named soc (the battery's charge, 54) showed "54 C, warm" as its hottest sensor."""
        text = "soc 54\ncpu-0-0-usr 38500\nbattery 36000\n"
        hottest = max(monitor.parse_thermal(text), key=lambda s: s[1])
        self.assertEqual(hottest, ("cpu-0-0-usr", 38.5))

    def test_the_temperature_of_each_part_of_the_chip_is_its_hottest_sensor(self):
        """From a Snapdragon phone's real sensor names: cores, cluster, GPU and memory sensors, plus limiters."""
        sensors = [("cpu-0-0-usr", 48.5), ("cpu-0-4-usr", 50.4), ("cpuss-1-usr", 50.7), ("cpu-0-max-step", 99.0),
                   ("gpuss-0-usr", 45.9), ("gpuss-max-step", 99.0), ("ddr-0-usr", 47.0), ("ddr-1-usr", 48.6),
                   ("battery", 38.0), ("pm6150-ibat-lvl0", 70.0)]
        self.assertEqual(monitor.soc_temps(sensors), {"cpu_temp": 50.7, "gpu_temp": 45.9, "ram_temp": 48.6})

    def test_a_part_without_a_sensor_is_left_out_not_guessed(self):
        self.assertEqual(monitor.soc_temps([("battery", 38.0), ("skin", 41.0)]), {})
        self.assertEqual(monitor.soc_temps([("cpu_thermal", 55.0)]), {"cpu_temp": 55.0})


class FakePhone:
    def __init__(self):
        self.n = 0

    def shell(self, command, timeout_ms=0):
        if command.startswith("top"):
            return TOP
        self.n += 1
        busy = 100 * self.n
        parts = [f"cpu  {busy} 0 0 {1000 * self.n - busy} 0 0 0 0",
                 "MemTotal: 4194304 kB\nMemAvailable: 1048576 kB",
                 "  level: 80\n  voltage: 4000\n  temperature: 300\n  status: 3\n",
                 "-450000",
                 f" wlan0: {self.n * 10240} 1 0 0 0 0 0 0 {self.n * 2048} 1 0 0 0 0 0 0",
                 "1800000\n1100000",
                 "cpu 41000\nbattery 30000"]
        return "".join("@@m@@\n" + p + "\n" for p in parts)


class MonitorTests(unittest.TestCase):
    def test_the_first_sample_already_has_a_load_but_network_rates_need_a_second(self):
        """The load is read against a quick baseline taken first, so the gauge does not wait for a second sample
        (over USB a sample takes several seconds). Network speed is still a rate over time."""
        mon = monitor.Monitor(FakePhone())
        first = mon.sample()
        self.assertAlmostEqual(first["cpu"], 10.0)
        self.assertNotIn("net_down_kbs", first)
        self.assertEqual(first["mem_pct"], 75.0)
        self.assertEqual(first["current_ma"], -450)
        self.assertEqual(first["hottest"], ("cpu", 41.0))
        time.sleep(0.05)                                     # Windows' clock ticks every 15 ms: rates need time to pass
        second = mon.sample()
        self.assertAlmostEqual(second["cpu"], 10.0)         # 100 busy of 1000 total jiffies
        self.assertGreater(second["net_down_kbs"], 0)
        self.assertEqual(first["top"][0][0], "com.example.video")
        self.assertNotIn("top", second)                      # `top` only every third sample


if __name__ == "__main__":
    unittest.main()


class TaskManagerTests(unittest.TestCase):
    def test_cpu_cores(self):
        text = "cpu  100 0 50 800 50 0 0 0\ncpu0 10 0 5 80 5 0 0 0\ncpu1 20 0 5 70 5 0 0 0\nintr 12345"
        cores = monitor.parse_cpu_cores(text)
        self.assertEqual(set(cores), {"cpu", "cpu0", "cpu1"})
        self.assertEqual(cores["cpu0"], (15, 100))

    def test_sizes(self):
        self.assertAlmostEqual(monitor.parse_size_mb("200M"), 200)
        self.assertAlmostEqual(monitor.parse_size_mb("1.5G"), 1536)
        self.assertAlmostEqual(monitor.parse_size_mb("2048K"), 2)
        self.assertAlmostEqual(monitor.parse_size_mb("1024"), 1)       # a plain number is KiB
        self.assertIsNone(monitor.parse_size_mb("n/a"))

    def test_classify(self):
        self.assertEqual(monitor.classify_process("u0_a123", "com.example.app"), "app")
        self.assertEqual(monitor.classify_process("system", "system_server"), "system")
        self.assertEqual(monitor.classify_process("root", "[kworker/u16:0]"), "kernel")
        self.assertEqual(monitor.classify_process("root", "ksoftirqd/3"), "kernel")

    def test_process_list(self):
        rows, total = monitor.parse_processes(TOP)
        self.assertEqual(total, 500)
        by_name = {r["name"]: r for r in rows}
        self.assertNotIn("top", by_name)                          # our own reading
        app = by_name["com.example.video"]
        self.assertEqual((app["pid"], app["user"], app["state"], app["kind"]), (4242, "u0_a123", "S", "app"))
        self.assertEqual(app["cpu"], 35.5)
        self.assertAlmostEqual(app["mem_mb"], 200)
        self.assertEqual(by_name["system_server"]["kind"], "system")
        self.assertEqual(monitor.parse_processes("nothing useful"), ([], None))

    def test_gpu_qualcomm_and_mali(self):
        out = monitor.parse_gpu("37 %", "490000000", "840000000", "", "")
        self.assertEqual((out["gpu_pct"], out["gpu_mhz"], out["gpu_max_mhz"]), (37, 490, 840))
        out = monitor.parse_gpu("", "", "", "55", "")
        self.assertEqual(out["gpu_pct"], 55)
        out = monitor.parse_gpu("", "", "", "", "gpubw 100 200\nsoc:qcom,gpu-llcc 5 6\nsoc:qcom,kgsl-3d0 400000000 800000000")
        self.assertEqual((out["gpu_mhz"], out["gpu_max_mhz"]), (400, 800))
        self.assertEqual(monitor.parse_gpu("", "", "", "", ""), {})

    def test_sample_has_core_usage_sensors_and_processes(self):
        class Phone(FakePhone):
            def shell(self, command, timeout_ms=0):
                if command.startswith("top"):
                    return TOP
                self.n += 1
                busy = 100 * self.n
                lines = "\n".join(f"{name}  {busy + k} 0 0 {1000 * self.n - busy - k} 0 0 0 0"
                                  for k, name in enumerate(("cpu", "cpu0", "cpu1")))
                parts = [lines, "MemTotal: 4194304 kB\nMemAvailable: 1048576 kB", "  level: 80\n", "", "", "1800000",
                         "cpu 41000\nbattery 30000\nGPU 52000", "", "", "37", "490000000", "840000000", "", ""]
                return "".join("@@m@@\n" + p + "\n" for p in parts)

        mon = monitor.Monitor(Phone())
        mon.sample()
        second = mon.sample()
        self.assertEqual(len(second["core_pct"]), 2)
        self.assertEqual(second["gpu_pct"], 37)
        self.assertEqual(second["thermal"][0], ("GPU", 52.0))      # hottest first
        self.assertNotIn("procs", second)                           # the list comes every other reading
        self.assertTrue(mon.sample()["procs"])
