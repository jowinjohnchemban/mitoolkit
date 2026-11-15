"""Connection diagnostics for a running phone: Wi-Fi, the modem and mobile network, the SIM,
Bluetooth, USB and power, and what is connected to each. Meant for finding out why Wi-Fi, mobile data
or calls misbehave.

Read-only. It reads `cmd wifi`, `dumpsys wifi / connectivity / telephony.registry / bluetooth_manager /
usb / battery`, `ip` and a few system properties, in one adb round trip. Android's dump formats differ
between versions and makers, so every parser is tolerant: a value it cannot find is simply left out.
The only thing that sends traffic is network_test(), and only when the user presses its button.

Values are rows (label, value, level). level is "ok", "warn", "bad" or None (just information), so the
window can mark each one with a word and a symbol as well as a colour.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

Row = Tuple[str, str, Optional[str]]
Section = Tuple[str, List[Row]]
Finding = Tuple[str, str, str]            # (level, what we found, what to do about it)

OK, WARN, BAD = "ok", "warn", "bad"
_MARK = "@@diag@@"
_UNKNOWN = 2147483647                     # Android's "no value" for signal readings

WIFI_STANDARDS = {"1": "Wi-Fi legacy (802.11a/b/g)", "4": "Wi-Fi 4 (802.11n)", "5": "Wi-Fi 5 (802.11ac)",
                  "6": "Wi-Fi 6 (802.11ax)", "7": "802.11ad", "8": "Wi-Fi 7 (802.11be)"}
WIFI_SECURITY = {"0": "Open (no password)", "1": "WEP", "2": "WPA / WPA2 (password)", "3": "Enterprise (EAP)",
                 "4": "WPA3 (SAE)", "5": "Enhanced Open (OWE)", "6": "WPA3 Enterprise", "7": "WPA3 Enterprise 192-bit"}
NETWORK_TYPES = {"1": "GPRS (2G)", "2": "EDGE (2G)", "3": "UMTS (3G)", "4": "CDMA (2G)", "8": "HSDPA (3G)",
                 "9": "HSUPA (3G)", "10": "HSPA (3G)", "13": "LTE (4G)", "15": "HSPA+ (3G)", "16": "GSM (2G)",
                 "17": "TD-SCDMA (3G)", "18": "IWLAN", "19": "LTE-Advanced (4G+)", "20": "NR (5G)"}
# What the status bar shows (TelephonyDisplayInfo): 5G can ride on a 4G connection ("non-standalone")
DISPLAY_NETWORKS = {"NR_NSA": "5G (non-standalone)", "NR_ADVANCED": "5G+", "LTE_CA": "4G+", "LTE_ADVANCED_PRO": "4G+ (Pro)",
                    "NONE": "", "UNKNOWN": "", "LTE": "4G", "NR": "5G", "UMTS": "3G", "HSPA": "3G", "GSM": "2G"}
REGISTRATION = {"0": "In service", "1": "No service", "2": "Searching", "3": "Emergency calls only", "4": "Out of service"}
DATA_STATES = {"0": "Disconnected", "1": "Connecting", "2": "Connected", "3": "Suspended", "4": "Disconnecting"}
CALL_STATES = {"0": "Idle", "1": "Ringing", "2": "In a call"}


# ------------------------------------------------------------------ helpers
def _num(text: Optional[str]) -> Optional[int]:
    """An int from text, or None (also for Android's "unknown" placeholder)."""
    m = re.match(r"\s*(-?\d+)", text or "")            # "5180MHz" -> 5180, "-61" -> -61
    if not m:
        return None
    value = int(m.group(1))
    return None if abs(value) >= _UNKNOWN - 1 else value


def wifi_band(mhz: Optional[int]) -> Tuple[str, Optional[int]]:
    """("5 GHz", 36) for 5180 MHz."""
    if not mhz:
        return "", None
    if 2400 <= mhz <= 2500:
        return "2.4 GHz", 14 if mhz == 2484 else (mhz - 2407) // 5
    if 5000 <= mhz < 5925:
        return "5 GHz", (mhz - 5000) // 5
    if 5925 <= mhz <= 7125:
        return "6 GHz", (mhz - 5950) // 5
    return f"{mhz} MHz", None


def rate_wifi_signal(rssi: Optional[int]) -> Tuple[str, Optional[str]]:
    if rssi is None:
        return "", None
    if rssi >= -55:
        return "Excellent", OK
    if rssi >= -67:
        return "Good", OK
    if rssi >= -75:
        return "Fair", WARN
    return "Weak", BAD


def rate_lte_rsrp(rsrp: Optional[int]) -> Tuple[str, Optional[str]]:
    if rsrp is None:
        return "", None
    if rsrp >= -90:
        return "Excellent", OK
    if rsrp >= -105:
        return "Good", OK
    if rsrp >= -115:
        return "Fair", WARN
    return "Poor", BAD


def rate_quality(rsrq: Optional[int]) -> Tuple[str, Optional[str]]:
    if rsrq is None:
        return "", None
    return ("Good", OK) if rsrq >= -10 else ("Fair", OK) if rsrq >= -15 else ("Poor", WARN)


def rate_sinr(sinr: Optional[int]) -> Tuple[str, Optional[str]]:
    if sinr is None:
        return "", None
    return ("Excellent", OK) if sinr >= 13 else ("Good", OK) if sinr >= 0 else ("Poor", WARN)


# -------------------------------------------------------------------- Wi-Fi
_WIFI_KEYS = ("SSID", "BSSID", "MAC", "Security type", "Supplicant state", "Wi-Fi standard", "RSSI", "Link speed",
              "Tx Link speed", "Rx Link speed", "Max Supported Tx Link speed", "Max Supported Rx Link speed",
              "Frequency", "Net ID", "Metered hint", "score", "Hidden")


def parse_wifi_info(text: str) -> Dict[str, str]:
    """The connected network from `cmd wifi status` or `dumpsys wifi` ("WifiInfo: SSID: "Home", BSSID: ...")."""
    start = text.find("SSID")
    if start < 0:
        return {}
    body = text[start:]
    body = body.split("\n", 1)[0] if "BSSID" in body.split("\n", 1)[0] else body[:1500]
    out: Dict[str, str] = {}
    for key in sorted(_WIFI_KEYS, key=len, reverse=True):
        m = re.search(r'(?<![\w-])' + re.escape(key) + r'\s*[:=]\s*("[^"]*"|[^,\n]+)', body)
        if m and key not in out:
            out[key] = m.group(1).strip().strip('"')
    return out


def parse_scan_results(text: str, limit: int = 12) -> List[Dict[str, object]]:
    """Nearby networks from `cmd wifi list-scan-results` (BSSID, frequency, RSSI, age, SSID, flags)."""
    rows: List[Dict[str, object]] = []
    for line in text.splitlines():
        m = re.match(r"\s*([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\s+(\d+)\s+(-?\d+)(?:\([^)]*\))?\s+[\d.]+\s+(.*?)\s{2,}(\[.*\])?\s*$",
                     line)
        if m:
            mhz, rssi = int(m.group(2)), int(m.group(3))
            band, channel = wifi_band(mhz)
            rows.append({"bssid": m.group(1), "mhz": mhz, "band": band, "channel": channel, "rssi": rssi,
                         "ssid": m.group(4).strip() or "(hidden)", "flags": m.group(5) or ""})
    rows.sort(key=lambda r: -r["rssi"])  # type: ignore[operator]
    return rows[:limit]


def channel_crowding(scan: List[Dict[str, object]], channel: Optional[int], band: str) -> int:
    """How many other nearby networks use the same channel (a crowded channel slows Wi-Fi down)."""
    return sum(1 for r in scan if r["channel"] == channel and r["band"] == band)


# ------------------------------------------------- connectivity (all networks)
def parse_networks(text: str) -> List[Dict[str, object]]:
    """The networks Android knows (`dumpsys connectivity`): type, state, interface, addresses, DNS,
    capabilities and whether Android has checked that the internet is reachable (VALIDATED)."""
    nets: List[Dict[str, object]] = []
    active = re.search(r"Active default network:\s*(\d+)", text)
    for line in text.splitlines():
        if "NetworkAgentInfo" not in line:
            continue
        net: Dict[str, object] = {}
        m = re.search(r"type:\s*(\w+)\[([^\]]*)\]", line)
        net["type"] = m.group(1) if m else ""
        net["subtype"] = m.group(2) if m else ""
        m = re.search(r"state:\s*(\w+)", line)
        net["state"] = m.group(1) if m else ""
        m = re.search(r"network\{(\d+)\}", line)
        net["id"] = m.group(1) if m else ""
        m = re.search(r"Capabilities:\s*([A-Z_&]+)", line)
        caps = m.group(1).split("&") if m else []
        net["capabilities"] = caps
        net["validated"] = "VALIDATED" in caps
        net["internet"] = "INTERNET" in caps
        net["metered"] = "NOT_METERED" not in caps and bool(caps)
        m = re.search(r"Transports:\s*(\w+)", line)
        net["transport"] = m.group(1) if m else net["type"]
        m = re.search(r"SignalStrength:\s*(-?\d+)", line)
        net["signal"] = _num(m.group(1)) if m else None
        lp = parse_link_properties(line)
        net.update(lp)
        net["default"] = bool(active and net["id"] == active.group(1))
        nets.append(net)
    return nets


def parse_link_properties(text: str) -> Dict[str, object]:
    """Interface, addresses, DNS servers, domains, MTU and routes from a LinkProperties dump."""
    out: Dict[str, object] = {}
    m = re.search(r"InterfaceName:\s*(\S+)", text)
    if m:
        out["interface"] = m.group(1)
    m = re.search(r"LinkAddresses:\s*\[([^\]]*)\]", text)
    if m:
        out["addresses"] = [a.strip().split("/")[0] for a in m.group(1).split(",") if a.strip()]
    m = re.search(r"DnsAddresses:\s*\[([^\]]*)\]", text)
    if m:
        out["dns"] = [a.strip().lstrip("/") for a in m.group(1).split(",") if a.strip()]
    m = re.search(r"Domains:\s*([^\s]+)", text)
    if m and m.group(1) != "null":
        out["domains"] = m.group(1)
    m = re.search(r"MTU:\s*(\d+)", text)
    if m:
        out["mtu"] = int(m.group(1))
    m = re.search(r"Routes:\s*\[([^\]]*)\]", text)
    if m:
        # the default route's next hop (0.0.0.0/0 or ::/0), not the on-link routes that also say "->"
        gateways = re.findall(r"(?:0\.0\.0\.0/0|::/0)\s*->\s*([0-9a-fA-F:.]+)", m.group(1))
        out["gateway"] = next((g for g in gateways if "." in g), gateways[0] if gateways else "")
    return out


# ---------------------------------------------------------- modem / telephony
def parse_telephony(text: str) -> Dict[str, object]:
    """The first SIM slot's state from `dumpsys telephony.registry`: registration, operator, network
    type, signal readings (RSRP, RSRQ, SINR, level), the cell the phone is on, data and call state."""
    out: Dict[str, object] = {}

    def first(pattern: str, flags: int = 0) -> Optional[str]:
        m = re.search(pattern, text, flags)
        return m.group(1) if m else None

    out["voice_reg"] = first(r"mVoiceRegState=(\d+)") or first(r"voiceRegState=(\d+)")
    out["data_reg"] = first(r"mDataRegState=(\d+)") or first(r"dataRegState=(\d+)")
    out["operator"] = first(r"mOperatorAlphaLong=([^\s,}]+(?: [^\s,}=]+)*?)(?=\s+m\w+=|,|\})")
    out["numeric"] = first(r"mOperatorNumeric=(\d+)")
    out["roaming"] = (first(r"mDataRoaming=(true|false)") or first(r"mVoiceRoaming=(true|false)") or "") == "true"
    out["data_state"] = first(r"mDataConnectionState=(\d+)")
    out["network_type"] = first(r"mDataConnectionNetworkType=(\d+)") or first(r"mNetworkType=(\d+)")
    out["call_state"] = first(r"mCallState=(\d+)")
    display = re.search(r"TelephonyDisplayInfo\s*\{\s*network=(\w+)(?:,\s*overrideNetwork=(\w+))?", text)
    if display:
        out["display_network"] = display.group(1)
        out["override_network"] = display.group(2)
    # signal: the 4G (LTE) block first, then 5G (NR)
    lte = re.search(r"CellSignalStrengthLte:([^\n]*)", text)
    nr = re.search(r"CellSignalStrengthNr:([^\n]*)", text)
    for tag, block in (("lte", lte), ("nr", nr)):
        if not block:
            continue
        body = block.group(1)
        for key, name in (("rsrp", "rsrp"), ("rsrq", "rsrq"), ("rssnr", "sinr"), ("ssRsrp", "rsrp"), ("ssRsrq", "rsrq"),
                          ("ssSinr", "sinr"), ("rssi", "rssi"), ("cqi", "cqi"), ("ta", "ta"), ("level", "level")):
            m = re.search(r"\b" + key + r"=(-?\d+)", body)
            value = _num(m.group(1)) if m else None
            if value is not None:
                out[f"{tag}_{name}"] = value
    gsm = re.search(r"CellSignalStrengthGsm:([^\n]*)", text)
    if gsm:
        m = re.search(r"\brssi=(-?\d+)", gsm.group(1))
        if m and _num(m.group(1)) is not None:
            out["gsm_rssi"] = _num(m.group(1))
    # the cell
    cell: Dict[str, str] = {}
    for key, label in (("mCi", "cell id"), ("mPci", "pci"), ("mTac", "tac"), ("mEarfcn", "earfcn"), ("mNci", "nci"),
                       ("mNrarfcn", "nrarfcn"), ("mLac", "lac"), ("mCid", "cid")):
        m = re.search(r"\b" + key + r"=(-?\d+)", text)
        if m and _num(m.group(1)) is not None:
            cell[label] = m.group(1)
    bands = re.search(r"mBands=\[([^\]]*)\]", text)
    if bands and bands.group(1).strip():
        cell["bands"] = bands.group(1).replace(" ", "")
    out["cell"] = cell
    mcc, mnc = first(r"mMcc=(\d+)"), first(r"mMnc=(\d+)")
    if mcc and mnc:
        out["mccmnc"] = mcc + mnc
    return out


# --------------------------------------------------------------- Bluetooth
def parse_bluetooth(text: str) -> Dict[str, object]:
    out: Dict[str, object] = {}
    m = re.search(r"\benabled:\s*(true|false)", text)
    if m:
        out["enabled"] = m.group(1) == "true"
    m = re.search(r"\bstate:\s*(\w+)", text)
    if m:
        out["state"] = m.group(1)
    m = re.search(r"\bname:\s*(.+)", text)
    if m:
        out["name"] = m.group(1).strip()
    bonded = re.findall(r"^\s*([0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5})\s*\[[^\]]*\]\s*(.*)$", text, re.M)
    out["bonded"] = [(addr, name.strip() or "(no name)") for addr, name in bonded]
    return out


# ----------------------------------------------------------------- USB, power
def parse_usb(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for key in ("connected", "configured", "current_functions", "data_role", "power_role", "host_connected"):
        m = re.search(r"\b" + key + r"\W+([\w,]+)", text)
        if m:
            out[key] = m.group(1)
    return out


# ------------------------------------------------------------------- tests
def parse_ping(text: str) -> Dict[str, object]:
    """Result of `ping`: packets sent and received, loss and average round trip."""
    out: Dict[str, object] = {}
    m = re.search(r"(\d+) packets transmitted, (\d+)(?: packets)? received", text)
    if m:
        out["sent"], out["received"] = int(m.group(1)), int(m.group(2))
        out["loss"] = round(100 * (1 - out["received"] / out["sent"])) if out["sent"] else 100  # type: ignore[operator]
    m = re.search(r"min/avg/max(?:/mdev)? = [\d.]+/([\d.]+)/", text)
    if m:
        out["avg_ms"] = float(m.group(1))
    out["unknown_host"] = "unknown host" in text.lower() or "bad address" in text.lower()
    return out


def ping_row(label: str, result: Dict[str, object]) -> Row:
    if result.get("unknown_host"):
        return label, "Name lookup failed: DNS is not working", BAD
    if "sent" not in result:
        return label, "No answer (the phone has no route there)", BAD
    loss, avg = result["loss"], result.get("avg_ms")
    text = f"{result['received']} of {result['sent']} replies" + (f", {avg:.0f} ms" if avg is not None else "")
    level = BAD if loss == 100 else WARN if loss or (avg or 0) > 150 else OK  # type: ignore[operator]
    return label, text, level


# ------------------------------------------------------------ collection
_COMMANDS = [
    "settings get global airplane_mode_on",
    "settings get global wifi_on",
    "settings get global mobile_data",
    "settings get global data_roaming",
    "cmd wifi status",
    "dumpsys wifi | grep -m2 -E 'mWifiInfo|WifiInfo:'",
    "cmd wifi list-scan-results",
    "dumpsys connectivity | grep -E 'Active default network|NetworkAgentInfo' | head -n 40",
    "dumpsys telephony.registry | head -n 400",
    "ip route",
    "getprop",
    "dumpsys bluetooth_manager | head -n 160",
    "dumpsys usb | head -n 80",
    "dumpsys battery",
    "cat /sys/class/power_supply/usb/real_type",
    "cat /sys/class/power_supply/usb/current_max",
]


def collect_raw(phone, timeout_ms: int = 60000) -> Dict[str, str]:
    """One adb round trip that reads everything above. Returns {command: output}."""
    raw = phone.shell("; ".join(f"echo {_MARK}; {c} 2>/dev/null" for c in _COMMANDS), timeout_ms)
    parts = [p.strip() for p in raw.split(_MARK)[1:]]
    parts += [""] * (len(_COMMANDS) - len(parts))
    return dict(zip(_COMMANDS, parts))


def build(raw: Dict[str, str]) -> Dict[str, object]:
    """Turn the raw readings into a report: {"sections": [...], "findings": [...], "signals": {...}}."""
    airplane = raw["settings get global airplane_mode_on"].strip() == "1"
    wifi_on = raw["settings get global wifi_on"].strip() in ("1", "2")
    data_on = raw["settings get global mobile_data"].strip() == "1"

    status = raw["cmd wifi status"] or raw["dumpsys wifi | grep -m2 -E 'mWifiInfo|WifiInfo:'"]
    wifi = parse_wifi_info(status)
    scan = parse_scan_results(raw["cmd wifi list-scan-results"])
    networks = parse_networks(raw["dumpsys connectivity | grep -E 'Active default network|NetworkAgentInfo' | head -n 40"])
    tele = parse_telephony(raw["dumpsys telephony.registry | head -n 400"])
    props = _props(raw["getprop"])
    bt = parse_bluetooth(raw["dumpsys bluetooth_manager | head -n 160"])
    usb = parse_usb(raw["dumpsys usb | head -n 80"])

    wifi_net = next((n for n in networks if n.get("transport") == "WIFI" or n.get("type") == "WIFI"), {})
    mobile_net = next((n for n in networks if n.get("transport") == "CELLULAR" or n.get("type") == "MOBILE"), {})

    sections: List[Section] = [
        ("Wi-Fi", _wifi_rows(wifi, wifi_net, scan, wifi_on, airplane, raw)),
        ("Wi-Fi networks nearby", _scan_rows(scan, wifi)),
        ("Mobile network", _mobile_rows(tele, mobile_net, props, data_on, airplane, raw)),
        ("SIM card", _sim_rows(props)),
        ("Bluetooth", _bluetooth_rows(bt)),
        ("Power and USB", _power_rows(usb, raw)),
        ("Networks Android is using", _network_rows(networks)),
    ]
    sections = [(title, rows) for title, rows in sections if rows]
    report: Dict[str, object] = {
        "sections": sections,
        "signals": {"wifi_dbm": _num(wifi.get("RSSI")), "mobile_dbm": tele.get("lte_rsrp") or tele.get("nr_rsrp")},
        "state": {"airplane": airplane, "wifi_on": wifi_on, "data_on": data_on},
    }
    report["findings"] = findings(wifi, wifi_net, mobile_net, tele, props, airplane, wifi_on, data_on, networks)
    return report


def _props(text: str) -> Dict[str, str]:
    return {m.group(1): m.group(2) for line in text.splitlines()
            if (m := re.match(r"\[(.+?)\]: \[(.*)\]", line.strip()))}


def _wifi_rows(wifi, net, scan, wifi_on: bool, airplane: bool, raw) -> List[Row]:
    rows: List[Row] = [("Wi-Fi switch", "On" if wifi_on else "Off", None if wifi_on else WARN)]
    if airplane:
        rows.append(("Airplane mode", "On: Wi-Fi and mobile radios are off", BAD))
    ssid = wifi.get("SSID", "")
    state = wifi.get("Supplicant state", "")
    if not ssid or ssid in ("<unknown ssid>", "0x") or state in ("DISCONNECTED", "INACTIVE", "SCANNING"):
        if wifi_on:
            rows.append(("Connection", f"Not connected{f' ({state.lower()})' if state else ''}", WARN))
        return rows
    rssi = _num(wifi.get("RSSI"))
    word, level = rate_wifi_signal(rssi)
    band, channel = wifi_band(_num(wifi.get("Frequency")))
    rows += [("Connected to", ssid, OK), ("Router (BSSID)", wifi.get("BSSID", ""), None)]
    if rssi is not None:
        rows.append(("Signal", f"{rssi} dBm ({word})", level))
    if band:
        rows.append(("Band and channel", f"{band}, channel {channel}" if channel else band, None))
        crowd = channel_crowding(scan, channel, band)
        if crowd >= 3:
            rows.append(("Channel crowding", f"{crowd} other networks on this channel: it may be slow", WARN))
    for key, label in (("Link speed", "Link speed"), ("Tx Link speed", "Send speed"), ("Rx Link speed", "Receive speed"),
                       ("Max Supported Tx Link speed", "Fastest the phone can send"),
                       ("Max Supported Rx Link speed", "Fastest the phone can receive")):
        if wifi.get(key) and wifi[key] not in ("-1Mbps", "-1"):
            rows.append((label, wifi[key], None))
    if wifi.get("Wi-Fi standard"):
        rows.append(("Wi-Fi generation", WIFI_STANDARDS.get(wifi["Wi-Fi standard"], wifi["Wi-Fi standard"]), None))
    if wifi.get("Security type"):
        sec = WIFI_SECURITY.get(wifi["Security type"], wifi["Security type"])
        rows.append(("Security", sec, BAD if wifi["Security type"] in ("0", "1") else None))
    if wifi.get("MAC"):
        rows.append(("Phone's Wi-Fi address", wifi["MAC"], None))
    rows += _network_detail(net)
    if net:
        rows.append(("Internet check", "Android reached the internet through this Wi-Fi" if net.get("validated")
                     else "Connected, but Android could not confirm internet access", OK if net.get("validated") else BAD))
    return rows


def _network_detail(net: Dict[str, object]) -> List[Row]:
    rows: List[Row] = []
    if net.get("addresses"):
        rows.append(("Phone's address", ", ".join(net["addresses"]), None))  # type: ignore[arg-type]
    if net.get("gateway"):
        rows.append(("Gateway (router)", str(net["gateway"]), None))
    if net.get("dns"):
        rows.append(("DNS servers", ", ".join(net["dns"]), None))  # type: ignore[arg-type]
    elif net:
        rows.append(("DNS servers", "None given: names cannot be looked up", WARN))
    if net.get("mtu"):
        rows.append(("MTU", str(net["mtu"]), None))
    return rows


def _scan_rows(scan, wifi) -> List[Row]:
    mine = wifi.get("BSSID", "").lower()
    rows: List[Row] = []
    for r in scan:
        word, level = rate_wifi_signal(r["rssi"])  # type: ignore[arg-type]
        where = f"{r['band']} ch {r['channel']}" if r["channel"] else str(r["band"])
        rows.append((str(r["ssid"]) + ("  (connected)" if str(r["bssid"]).lower() == mine else ""),
                     f"{r['rssi']} dBm, {where}", level))
    return rows


def _mobile_rows(tele, net, props, data_on: bool, airplane: bool, raw) -> List[Row]:
    rows: List[Row] = []
    if airplane:
        rows.append(("Airplane mode", "On: the modem is off", BAD))
    if tele.get("voice_reg") is not None:
        reg = REGISTRATION.get(str(tele["voice_reg"]), str(tele["voice_reg"]))
        rows.append(("Calls (voice)", reg, OK if tele["voice_reg"] == "0" else BAD if tele["voice_reg"] in ("1", "4") else WARN))
    if tele.get("data_reg") is not None:
        reg = REGISTRATION.get(str(tele["data_reg"]), str(tele["data_reg"]))
        rows.append(("Mobile data registration", reg, OK if tele["data_reg"] == "0" else BAD if tele["data_reg"] in ("1", "4") else WARN))
    operator = tele.get("operator") or props.get("gsm.operator.alpha", "")
    if operator:
        numeric = tele.get("numeric") or props.get("gsm.operator.numeric", "")
        rows.append(("Operator", f"{operator}" + (f" ({numeric})" if numeric else ""), None))
    ntype = NETWORK_TYPES.get(str(tele.get("network_type")), "")
    shown = tele.get("override_network") or tele.get("display_network")
    shown = DISPLAY_NETWORKS.get(str(shown), "") if shown else ""
    if ntype or shown:
        rows.append(("Network type", ntype + (f"; the status bar shows {shown}" if shown and shown != ntype else ""), None))
    if tele.get("roaming"):
        rows.append(("Roaming", "Yes: charges may apply", WARN))
    rows.append(("Mobile data switch", "On" if data_on else "Off", None if data_on else WARN))
    if tele.get("data_state") is not None:
        state = DATA_STATES.get(str(tele["data_state"]), str(tele["data_state"]))
        rows.append(("Data link", state, OK if tele["data_state"] == "2" else WARN if data_on else None))
    if tele.get("call_state") is not None:
        rows.append(("Call state", CALL_STATES.get(str(tele["call_state"]), str(tele["call_state"])), None))
    for tag, name in (("lte", "4G (LTE)"), ("nr", "5G (NR)")):
        rsrp, rsrq, sinr = tele.get(f"{tag}_rsrp"), tele.get(f"{tag}_rsrq"), tele.get(f"{tag}_sinr")
        if rsrp is not None:
            word, level = rate_lte_rsrp(rsrp)  # type: ignore[arg-type]
            rows.append((f"{name} signal (RSRP)", f"{rsrp} dBm ({word})", level))
        if rsrq is not None:
            word, level = rate_quality(rsrq)  # type: ignore[arg-type]
            rows.append((f"{name} quality (RSRQ)", f"{rsrq} dB ({word})", level))
        if sinr is not None:
            word, level = rate_sinr(sinr)  # type: ignore[arg-type]
            rows.append((f"{name} noise (SINR)", f"{sinr} dB ({word})", level))
        if tele.get(f"{tag}_level") is not None:
            rows.append((f"{name} signal bars", f"{tele[f'{tag}_level']} of 4", None))
        if tele.get(f"{tag}_ta") is not None:
            rows.append((f"{name} timing advance", str(tele[f"{tag}_ta"]), None))
    if tele.get("gsm_rssi") is not None:
        rows.append(("2G/3G signal (RSSI)", f"{tele['gsm_rssi']} dBm", None))
    cell = tele.get("cell") or {}
    labels = {"cell id": "Cell ID", "pci": "Physical cell ID (PCI)", "tac": "Tracking area (TAC)", "earfcn": "Channel (EARFCN)",
              "nci": "5G cell ID (NCI)", "nrarfcn": "5G channel (NR-ARFCN)", "bands": "Band", "lac": "Location area (LAC)",
              "cid": "Cell ID"}
    for key, value in cell.items():  # type: ignore[union-attr]
        rows.append((labels.get(key, key), str(value), None))
    for label, key in (("Modem (baseband)", "gsm.version.baseband"), ("Radio interface (RIL)", "gsm.version.ril-impl"),
                       ("Phone type", "gsm.current.phone-type")):
        if props.get(key):
            value = {"1": "GSM family (2G, 3G, 4G, 5G)", "2": "CDMA"}.get(props[key], props[key]) if key.endswith("phone-type") else props[key]
            rows.append((label, value, None))
    rows += _network_detail(net) if net else []
    if net:
        rows.append(("Internet check", "Android reached the internet over mobile data" if net.get("validated")
                     else "Connected, but Android could not confirm internet access", OK if net.get("validated") else BAD))
    return rows


def _sim_rows(props) -> List[Row]:
    rows: List[Row] = []
    state = props.get("gsm.sim.state", "")
    if state:
        slots = [s.strip() for s in state.split(",")]
        for i, s in enumerate(slots, 1):
            level = OK if s == "READY" else WARN if s in ("ABSENT", "NOT_READY") else BAD if s in ("PIN_REQUIRED", "PUK_REQUIRED", "NETWORK_LOCKED", "CARD_IO_ERROR") else None
            words = {"READY": "Ready", "ABSENT": "No SIM inserted", "PIN_REQUIRED": "Locked: PIN needed",
                     "PUK_REQUIRED": "Locked: PUK needed", "NETWORK_LOCKED": "Network locked",
                     "NOT_READY": "Not ready yet", "LOADED": "Loaded", "CARD_IO_ERROR": "Card error: reseat the SIM"}.get(s, s)
            rows.append((f"SIM {i}" if len(slots) > 1 else "SIM state", words, level))
    for label, key in (("SIM operator", "gsm.sim.operator.alpha"), ("SIM code (MCC and MNC)", "gsm.sim.operator.numeric"),
                       ("SIM country", "gsm.sim.operator.iso-country"), ("SIM slots", "persist.radio.multisim.config")):
        if props.get(key):
            rows.append((label, props[key], None))
    return rows


def _bluetooth_rows(bt) -> List[Row]:
    rows: List[Row] = []
    if "enabled" in bt:
        rows.append(("Bluetooth", "On" if bt["enabled"] else "Off", None))
    if bt.get("state"):
        rows.append(("State", str(bt["state"]).replace("_", " ").title(), None))
    if bt.get("name"):
        rows.append(("Phone's Bluetooth name", str(bt["name"]), None))
    for addr, name in bt.get("bonded", []):  # type: ignore[union-attr]
        rows.append((f"Paired: {name}", addr, None))
    return rows


def _power_rows(usb, raw) -> List[Row]:
    rows: List[Row] = []
    battery = dict(re.findall(r"^\s*([A-Za-z ]+):\s*(\S.*)$", raw["dumpsys battery"], re.M))
    for label, key in (("AC charger", "AC powered"), ("USB power", "USB powered"), ("Wireless charger", "Wireless powered")):
        if key in battery:
            rows.append((label, "Connected" if battery[key].strip() == "true" else "Not connected", None))
    status = {"2": "Charging", "3": "Discharging", "4": "Not charging", "5": "Full"}.get(battery.get("status", "").strip())
    if status:
        rows.append(("Battery state", status, None))
    kind = raw["cat /sys/class/power_supply/usb/real_type"].strip()
    if kind and "No such" not in kind:
        rows.append(("Charger type", kind, None))
    current = raw["cat /sys/class/power_supply/usb/current_max"].strip()
    if current.isdigit() and int(current) > 0:
        rows.append(("Charger limit", f"{int(current) // 1000} mA", None))
    for key, label in (("connected", "USB connected"), ("configured", "USB configured"), ("current_functions", "USB mode"),
                       ("data_role", "USB data role"), ("power_role", "USB power role")):
        if usb.get(key):
            rows.append((label, usb[key], None))
    return rows


def _network_rows(networks) -> List[Row]:
    rows: List[Row] = []
    for n in networks:
        title = f"{n.get('transport') or n.get('type')} (network {n.get('id')})" + ("  default" if n.get("default") else "")
        bits = [str(n.get("interface", "")), ", ".join(n.get("addresses", [])[:2]) if n.get("addresses") else ""]  # type: ignore[index]
        flags = ("internet confirmed" if n.get("validated") else "no internet confirmed", "metered" if n.get("metered") else "")
        rows.append((title, "; ".join(b for b in bits + list(flags) if b), OK if n.get("validated") else WARN))
    return rows


# ----------------------------------------------------------------- findings
def findings(wifi, wifi_net, mobile_net, tele, props, airplane: bool, wifi_on: bool, data_on: bool,
             networks) -> List[Finding]:
    """What looks wrong, in plain words, worst first, with what to try."""
    out: List[Finding] = []
    if airplane:
        out.append((BAD, "Airplane mode is on", "Turn it off in the phone's quick settings: Wi-Fi, mobile data and calls are all off."))
    ssid = wifi.get("SSID", "")
    connected = bool(ssid) and ssid not in ("<unknown ssid>", "0x") and wifi.get("Supplicant state", "COMPLETED") not in ("DISCONNECTED", "INACTIVE", "SCANNING")
    rssi = _num(wifi.get("RSSI"))
    if wifi_on and not connected and not airplane:
        out.append((WARN, "Wi-Fi is on but not connected", "Check the network name and password, or move closer to the router."))
    if connected and rssi is not None and rssi < -75:
        out.append((BAD, f"Wi-Fi signal is weak ({rssi} dBm)", "Move closer to the router or remove obstacles; try the 2.4 GHz network for range."))
    elif connected and rssi is not None and rssi < -67:
        out.append((WARN, f"Wi-Fi signal is only fair ({rssi} dBm)", "Speed may drop in busy moments; moving closer helps."))
    if connected and wifi_net and not wifi_net.get("validated"):
        out.append((BAD, "Wi-Fi is connected but has no internet", "The router may have lost its connection, or the network needs a sign-in page. Restart the router; check the DNS servers below."))
    if connected and wifi_net and not wifi_net.get("dns"):
        out.append((WARN, "Wi-Fi gave the phone no DNS server", "Websites will not open by name. Forget and re-join the network, or set a DNS server."))
    if not airplane:
        sim = [s.strip() for s in props.get("gsm.sim.state", "").split(",") if s.strip()]
        if sim and all(s == "ABSENT" for s in sim):
            out.append((WARN, "No SIM card detected", "Insert or reseat the SIM; if it is in, try cleaning its contacts or another slot."))
        if any(s in ("PIN_REQUIRED", "PUK_REQUIRED") for s in sim):
            out.append((BAD, "The SIM is locked", "Enter the SIM PIN (or PUK) on the phone."))
        if tele.get("voice_reg") in ("1", "4") and "ABSENT" not in sim:
            out.append((BAD, "The phone has no mobile service", "Check coverage, toggle airplane mode, or restart the phone; try another SIM to rule out the SIM."))
        rsrp = tele.get("lte_rsrp") or tele.get("nr_rsrp")
        if isinstance(rsrp, int) and rsrp < -115:
            out.append((BAD, f"Mobile signal is poor ({rsrp} dBm)", "Move near a window or outside; calls and data may drop."))
        elif isinstance(rsrp, int) and rsrp < -105:
            out.append((WARN, f"Mobile signal is fair ({rsrp} dBm)", "Data may be slow indoors."))
        sinr = tele.get("lte_sinr") if tele.get("lte_sinr") is not None else tele.get("nr_sinr")
        if isinstance(sinr, int) and sinr < 0:
            out.append((WARN, f"Mobile signal is noisy (SINR {sinr} dB)", "Interference from nearby cells: speed will be low even with full bars."))
        if data_on and tele.get("data_state") in ("0", "3") and not connected and "ABSENT" not in sim:
            out.append((WARN, "Mobile data is on but not connected", "Check the APN settings, data limit and roaming; toggle mobile data off and on."))
        if tele.get("roaming"):
            out.append((WARN, "The phone is roaming", "Data and calls may cost extra; turn data roaming off if you did not mean to roam."))
        if mobile_net and not mobile_net.get("validated") and mobile_net.get("state", "").startswith("CONNECTED"):
            out.append((BAD, "Mobile data is connected but has no internet", "Check the APN, your plan and balance, and the signal."))
    order = {BAD: 0, WARN: 1, OK: 2}
    out.sort(key=lambda f: order[f[0]])
    if not out:
        out.append((OK, "No connection problems found", "Wi-Fi, mobile network and SIM look healthy."))
    return out


def network_test(phone, gateway: Optional[str] = None) -> List[Row]:
    """Ping the router, a public address, and look up a name, from the phone. This sends a few small
    packets, so it only runs when the user asks (the Network test button)."""
    rows: List[Row] = []
    if gateway and re.fullmatch(r"[0-9a-fA-F:.]+", gateway):  # it comes from the phone, but never trust it in a shell line
        rows.append(ping_row("Router (gateway)", parse_ping(phone.shell(f"ping -c 3 -W 2 {gateway}", 20000))))
    rows.append(ping_row("Internet (8.8.8.8)", parse_ping(phone.shell("ping -c 3 -W 2 8.8.8.8", 20000))))
    rows.append(ping_row("Name lookup (google.com)", parse_ping(phone.shell("ping -c 1 -W 3 google.com", 20000))))
    return rows


def run(phone) -> Dict[str, object]:
    """Read the phone and build the report (what the Connections window does)."""
    return build(collect_raw(phone))


# Rows that identify you or your place: names and addresses of networks and devices.
_PRIVATE_LABELS = {"Connected to", "Router (BSSID)", "Phone's Wi-Fi address", "Phone's address", "Gateway (router)",
                   "DNS servers", "Phone's Bluetooth name", "Wi-Fi IP address"}


def redact(report: Dict[str, object]) -> Dict[str, object]:
    """A copy without the rows that name your networks and devices (for AI agents, which only need the
    state and the signal): SSID, BSSID, addresses, DNS, nearby network names, paired Bluetooth devices."""
    sections: List[Section] = []
    for title, rows in report["sections"]:  # type: ignore[union-attr]
        clean: List[Row] = []
        for label, value, level in rows:
            if label.startswith("Paired:"):               # the device's name is in the label
                clean.append(("Paired device", "(hidden)", level))
            elif label in _PRIVATE_LABELS:
                clean.append((label, "(hidden)", level))
            elif title == "Wi-Fi networks nearby":
                clean.append(("(network name hidden)", re.sub(r"^[^,]*,", "", value).strip() or value, level))
            elif title == "Networks Android is using":     # keep the kind, interface and state; mask addresses
                masked = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b|(?:[0-9a-fA-F]{1,4}:){2,}[0-9a-fA-F]{0,4}", "(hidden)", value)
                clean.append((label, masked, level))
            else:
                clean.append((label, value, level))
        sections.append((title, clean))
    return {**report, "sections": sections}


def as_text(report: Dict[str, object]) -> str:
    lines: List[str] = []
    for level, title, advice in report.get("findings", []):  # type: ignore[union-attr]
        lines.append(f"[{level}] {title}: {advice}")
    for title, rows in report.get("sections", []):  # type: ignore[union-attr]
        lines += ["", f"[{title}]"] + [f"{label}: {value}" for label, value, _lvl in rows]
    return "\n".join(lines).strip()
