"""Connection diagnostics: parsing Wi-Fi, mobile network, SIM, Bluetooth and USB readings, and the
plain-language findings built from them."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mitoolkit import diagnostics as d  # noqa: E402

WIFI = ('WifiInfo: SSID: "Home Net", BSSID: a4:50:46:11:22:33, MAC: 02:00:00:aa:bb:cc, Security type: 4, '
        'Supplicant state: COMPLETED, Wi-Fi standard: 6, RSSI: -61, Link speed: 866Mbps, Tx Link speed: 866Mbps, '
        'Rx Link speed: 780Mbps, Max Supported Tx Link speed: 1200Mbps, Max Supported Rx Link speed: 1200Mbps, '
        'Frequency: 5180MHz, Net ID: 3, Metered hint: false, score: 60')

SCAN = """    BSSID              Frequency   RSSI           Age(sec)     SSID                                 Flags
  a4:50:46:11:22:33        5180    -61(0:-61/1:-62)   1.500    Home Net     [WPA2-PSK-CCMP][ESS]
  10:00:00:00:00:01        5180    -80(0:-80/1:-81)   1.500    Neighbour    [WPA2-PSK-CCMP][ESS]
  10:00:00:00:00:02        2437    -70(0:-70/1:-71)   2.000    Cafe         [ESS]
"""

NETS = (
    "Active default network: 100\n"
    "NetworkAgentInfo{ ni{[type: WIFI[], state: CONNECTED/CONNECTED, reason: (unspecified), extra: \"Home Net\"]} "
    "network{100}  nethandle{1} lp{{InterfaceName: wlan0 LinkAddresses: [ fe80::1/64,192.168.1.23/24, ] "
    "DnsAddresses: [ /192.168.1.1, /8.8.8.8, ] Domains: lan MTU: 1500 Routes: [ fe80::/64 -> :: wlan0,"
    "192.168.1.0/24 -> 0.0.0.0 wlan0,0.0.0.0/0 -> 192.168.1.1 wlan0 ]}} nc{[ Transports: WIFI Capabilities: "
    "NOT_METERED&INTERNET&NOT_RESTRICTED&TRUSTED&NOT_VPN&VALIDATED&NOT_ROAMING SignalStrength: -61]} }\n"
    "NetworkAgentInfo{ ni{[type: MOBILE[LTE], state: CONNECTED/CONNECTED, reason: connected, extra: internet]} "
    "network{101}  lp{{InterfaceName: rmnet_data1 LinkAddresses: [ 10.20.30.40/30, ] DnsAddresses: [ /10.0.0.1, ] "
    "Domains: null MTU: 1400 Routes: [ 0.0.0.0/0 -> 10.20.30.41 rmnet_data1 ]}} nc{[ Transports: CELLULAR Capabilities: "
    "INTERNET&NOT_RESTRICTED&TRUSTED&NOT_VPN&NOT_ROAMING SignalStrength: -98]} }\n"
)

TELE = """
  mCallState=0
  mDataConnectionState=2
  mDataConnectionNetworkType=13
  mServiceState={mVoiceRegState=0(IN_SERVICE), mDataRegState=0(IN_SERVICE), mOperatorAlphaLong=Jio 4G, mOperatorNumeric=405874, mDataRoaming=false}
  mTelephonyDisplayInfo=TelephonyDisplayInfo {network=LTE, overrideNetwork=NR_NSA}
  mSignalStrength=SignalStrength:{mCdma=Invalid, mLte=CellSignalStrengthLte: rssi=-70 rsrp=-98 rsrq=-11 rssnr=7 cqi=11 ta=2147483647 level=3 miscLevel=3}
  mCellIdentity=CellIdentityLte:{mCi=12345678 mPci=210 mTac=4242 mEarfcn=1850 mBands=[3] mMcc=405 mMnc=874}
"""

PING_OK = "3 packets transmitted, 3 received, 0% packet loss, time 2003ms\nrtt min/avg/max/mdev = 8.1/12.5/20.2/5.1 ms"
PING_LOST = "3 packets transmitted, 0 received, 100% packet loss, time 2010ms"


class WifiTests(unittest.TestCase):
    def test_connection_details(self):
        w = d.parse_wifi_info(WIFI)
        self.assertEqual((w["SSID"], w["BSSID"], w["RSSI"], w["Frequency"]), ("Home Net", "a4:50:46:11:22:33", "-61", "5180MHz"))
        self.assertEqual(w["Wi-Fi standard"], "6")
        self.assertEqual(w["Max Supported Tx Link speed"], "1200Mbps")
        self.assertEqual(w["Link speed"], "866Mbps")

    def test_band_channel_and_signal_words(self):
        self.assertEqual(d.wifi_band(5180), ("5 GHz", 36))
        self.assertEqual(d.wifi_band(2437), ("2.4 GHz", 6))
        self.assertEqual(d.wifi_band(5955), ("6 GHz", 1))
        self.assertEqual(d.rate_wifi_signal(-50), ("Excellent", d.OK))
        self.assertEqual(d.rate_wifi_signal(-72), ("Fair", d.WARN))
        self.assertEqual(d.rate_wifi_signal(-85), ("Weak", d.BAD))

    def test_scan_results_sorted_and_crowding(self):
        scan = d.parse_scan_results(SCAN)
        self.assertEqual([r["ssid"] for r in scan], ["Home Net", "Cafe", "Neighbour"])
        self.assertEqual(scan[0]["channel"], 36)
        self.assertEqual(d.channel_crowding(scan, 36, "5 GHz"), 2)


class NetworkTests(unittest.TestCase):
    def test_networks_dns_gateway_and_internet_check(self):
        nets = d.parse_networks(NETS)
        self.assertEqual([n["transport"] for n in nets], ["WIFI", "CELLULAR"])
        wifi, mobile = nets
        self.assertTrue(wifi["default"] and wifi["validated"])
        self.assertEqual(wifi["interface"], "wlan0")
        self.assertEqual(wifi["dns"], ["192.168.1.1", "8.8.8.8"])
        self.assertEqual(wifi["gateway"], "192.168.1.1")
        self.assertIn("192.168.1.23", wifi["addresses"])
        self.assertFalse(mobile["validated"])                # no VALIDATED capability: Android could not confirm internet
        self.assertEqual(mobile["signal"], -98)


class TelephonyTests(unittest.TestCase):
    def test_registration_operator_signal_and_cell(self):
        t = d.parse_telephony(TELE)
        self.assertEqual((t["voice_reg"], t["data_reg"], t["data_state"], t["network_type"]), ("0", "0", "2", "13"))
        self.assertEqual(t["operator"], "Jio 4G")
        self.assertEqual(t["numeric"], "405874")
        self.assertEqual((t["lte_rsrp"], t["lte_rsrq"], t["lte_sinr"], t["lte_level"]), (-98, -11, 7, 3))
        self.assertNotIn("lte_ta", t)                         # Android's "unknown" placeholder is dropped
        self.assertEqual(t["cell"]["pci"], "210")
        self.assertEqual(t["cell"]["bands"], "3")
        self.assertEqual(t["override_network"], "NR_NSA")

    def test_ratings(self):
        self.assertEqual(d.rate_lte_rsrp(-85)[1], d.OK)
        self.assertEqual(d.rate_lte_rsrp(-110)[1], d.WARN)
        self.assertEqual(d.rate_lte_rsrp(-120)[1], d.BAD)
        self.assertEqual(d.rate_sinr(-3)[1], d.WARN)


class OtherTests(unittest.TestCase):
    def test_bluetooth(self):
        bt = d.parse_bluetooth("  enabled: true\n  state: ON\n  name: POCO M2 Pro\nBonded devices:\n"
                               "  AA:BB:CC:DD:EE:FF [ DEVICE_TYPE_CLASSIC ] Headphones\n")
        self.assertEqual((bt["enabled"], bt["state"], bt["name"]), (True, "ON", "POCO M2 Pro"))
        self.assertEqual(bt["bonded"], [("AA:BB:CC:DD:EE:FF", "Headphones")])

    def test_usb_and_ping(self):
        self.assertEqual(d.parse_usb("connected: true\n configured=true\ncurrent_functions: mtp,adb")["current_functions"], "mtp,adb")
        ok, lost = d.parse_ping(PING_OK), d.parse_ping(PING_LOST)
        self.assertEqual((ok["sent"], ok["received"], ok["loss"], ok["avg_ms"]), (3, 3, 0, 12.5))
        self.assertEqual(d.ping_row("Internet", ok)[2], d.OK)
        self.assertEqual(d.ping_row("Internet", lost)[2], d.BAD)
        self.assertEqual(d.ping_row("Lookup", d.parse_ping("ping: unknown host google.com"))[2], d.BAD)


class ReportTests(unittest.TestCase):
    def raw(self, **changes):
        base = {c: "" for c in d._COMMANDS}
        base.update({"settings get global airplane_mode_on": "0", "settings get global wifi_on": "1",
                     "settings get global mobile_data": "1", "cmd wifi status": WIFI, "cmd wifi list-scan-results": SCAN,
                     "dumpsys connectivity | grep -E 'Active default network|NetworkAgentInfo' | head -n 40": NETS,
                     "dumpsys telephony.registry | head -n 400": TELE,
                     "getprop": "[gsm.sim.state]: [READY]\n[gsm.version.baseband]: [M2101]\n[gsm.current.phone-type]: [1]",
                     "dumpsys battery": "  USB powered: true\n  status: 2\n"})
        base.update(changes)
        return base

    def test_report_has_sections_with_levels(self):
        report = d.build(self.raw())
        sections = {t: {l: (v, lvl) for l, v, lvl in rows} for t, rows in report["sections"]}
        self.assertEqual(sections["Wi-Fi"]["Connected to"][0], "Home Net")
        self.assertEqual(sections["Wi-Fi"]["Signal"], ("-61 dBm (Good)", d.OK))
        self.assertEqual(sections["Wi-Fi"]["Band and channel"][0], "5 GHz, channel 36")
        self.assertEqual(sections["Wi-Fi"]["Gateway (router)"][0], "192.168.1.1")
        self.assertEqual(sections["Mobile network"]["Operator"][0], "Jio 4G (405874)")
        self.assertEqual(sections["Mobile network"]["4G (LTE) signal (RSRP)"], ("-98 dBm (Good)", d.OK))
        self.assertEqual(sections["SIM card"]["SIM state"], ("Ready", d.OK))
        self.assertEqual(sections["Power and USB"]["USB power"][0], "Connected")
        self.assertEqual(report["signals"], {"wifi_dbm": -61, "mobile_dbm": -98})

    def test_findings_name_the_problem_and_what_to_try(self):
        found = {title: level for level, title, _advice in d.build(self.raw())["findings"]}
        self.assertEqual(found["Mobile data is connected but has no internet"], d.BAD)   # not VALIDATED in NETS

    def test_healthy_phone_says_so(self):
        healthy = NETS.replace("INTERNET&NOT_RESTRICTED&TRUSTED&NOT_VPN&NOT_ROAMING", "INTERNET&VALIDATED&NOT_ROAMING")
        report = d.build(self.raw(**{"dumpsys connectivity | grep -E 'Active default network|NetworkAgentInfo' | head -n 40": healthy}))
        self.assertEqual(report["findings"][0][0], d.OK)

    def test_airplane_mode_and_weak_wifi_and_locked_sim(self):
        weak = WIFI.replace("RSSI: -61", "RSSI: -82")
        report = d.build(self.raw(**{"settings get global airplane_mode_on": "1", "cmd wifi status": weak,
                                     "getprop": "[gsm.sim.state]: [PIN_REQUIRED]"}))
        titles = [t for _l, t, _a in report["findings"]]
        self.assertIn("Airplane mode is on", titles)
        self.assertTrue(any(t.startswith("Wi-Fi signal is weak") for t in titles))
        self.assertEqual(report["findings"][0][0], d.BAD)                     # worst first

    def test_not_connected_wifi_and_no_sim(self):
        report = d.build(self.raw(**{"cmd wifi status": 'WifiInfo: SSID: <unknown ssid>, Supplicant state: DISCONNECTED',
                                     "getprop": "[gsm.sim.state]: [ABSENT]"}))
        titles = [t for _l, t, _a in report["findings"]]
        self.assertIn("Wi-Fi is on but not connected", titles)
        self.assertIn("No SIM card detected", titles)

    def test_copy_text_and_network_test_checks_the_gateway(self):
        text = d.as_text(d.build(self.raw()))
        self.assertIn("[Wi-Fi]", text)
        self.assertIn("Connected to: Home Net", text)

        class Phone:
            def __init__(self):
                self.calls = []

            def shell(self, command, timeout_ms=0):
                self.calls.append(command)
                return PING_OK

        phone = Phone()
        rows = d.network_test(phone, "192.168.1.1; reboot")        # not an address: never reaches a shell line
        self.assertEqual(len(rows), 2)
        self.assertFalse(any("reboot" in c for c in phone.calls))
        rows = d.network_test(phone, "192.168.1.1")
        self.assertEqual(len(rows), 3)


if __name__ == "__main__":
    unittest.main()
