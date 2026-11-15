"""Show more: IMEI parsing, battery, fastboot variables, and the sections for a fake phone."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from miunlock import details  # noqa: E402


def parcel(text: str) -> str:
    """What `service call iphonesubinfo` prints for a string."""
    words = ["00000000", f"{len(text):08x}"]
    units = [ord(c) for c in text] + [0] * (len(text) % 2)
    words += [f"{units[i + 1]:04x}{units[i]:04x}" for i in range(0, len(units), 2)]
    lines = []
    for n in range(0, len(words), 4):
        lines.append(f"  0x{n * 4:08x}: " + " ".join(words[n:n + 4]) + " '................'")
    return "Result: Parcel(\n" + "\n".join(lines) + ")"


GOOD_IMEI = "356831091234565"   # Luhn-valid
assert details.luhn_ok(GOOD_IMEI)


class ParsingTests(unittest.TestCase):
    def test_luhn(self):
        self.assertTrue(details.luhn_ok(GOOD_IMEI))
        self.assertFalse(details.luhn_ok("356831091234566"))
        self.assertFalse(details.luhn_ok("12345"))

    def test_parcel_string(self):
        self.assertEqual(details.parse_parcel_string(parcel(GOOD_IMEI)), GOOD_IMEI)
        self.assertIsNone(details.parse_parcel_string("Result: Parcel(00000001 ...)"))
        self.assertIsNone(details.parse_parcel_string(""))

    def test_battery(self):
        text = "Current Battery Service state:\n  AC powered: false\n  USB powered: true\n  status: 2\n  health: 2\n" \
               "  level: 66\n  voltage: 4012\n  temperature: 332\n  technology: Li-poly\n"
        rows = dict(details.parse_battery(text))
        self.assertEqual(rows["Charge"], "66%")
        self.assertEqual(rows["Status"], "Charging")
        self.assertEqual(rows["Health"], "Good")
        self.assertEqual(rows["Temperature"], "33.2 °C")
        self.assertEqual(rows["Power source"], "USB")

    def test_fastboot_vars(self):
        lines = ["(bootloader) product: gram", "version-bootloader: unknown", "(bootloader) serialno: FB1",
                 "all: ", "Finished. Total time: 0.01s", "junk line"]
        self.assertEqual(details.parse_fastboot_vars(lines),
                         [("product", "gram"), ("version-bootloader", "unknown"), ("serialno", "FB1")])


class FakePhone:
    serial = "6a81a217"

    def __init__(self, props, imei_reply=""):
        self.props, self.imei_reply = props, imei_reply

    def shell(self, command, timeout_ms=60000):
        parts = command.split("echo @@miunlock@@; ")[1:]
        out = []
        for part in parts:
            cmd = part.rstrip("; ").replace(" 2>/dev/null", "").strip()
            if cmd == "getprop":
                out.append("\n".join(f"[{k}]: [{v}]" for k, v in self.props.items()))
            elif cmd.startswith("service call iphonesubinfo 3 i32 0"):
                out.append(self.imei_reply)
            elif cmd == "settings get secure android_id":
                out.append("abcdef0123456789")
            elif cmd == "cat /sys/class/net/wlan0/address":
                out.append("a4:50:46:11:22:33")
            elif cmd == "dumpsys battery":
                out.append("  level: 50\n  voltage: 3900\n  temperature: 300\n  status: 3\n  health: 2\n")
            elif cmd == "cat /proc/uptime":
                out.append("7200.5 1000.0")
            elif cmd == "df -h":
                out.append("Filesystem Size Used Avail Use% Mounted on\n/dev/dm-1 5.5G 5.4G 90M 99% /\n"
                           "/dev/block/dm-9 45G 42G 3.0G 94% /data\n/dev/dm-2 1.2G 1.1G 100M 92% /vendor\n"
                           "/dev/block/dm-9 45G 42G 3.0G 94% /data\ntmpfs 2.7G 0 2.7G 0% /dev")
            elif cmd == "cat /proc/cmdline":
                out.append("console=ttyMSM0 androidboot.hwc=India androidboot.baseband=msm androidboot.bootloader=unknown")
            elif cmd == "settings get global airplane_mode_on":
                out.append("0")
            elif cmd == "settings get global wifi_on":
                out.append("1")
            elif cmd == "settings get secure location_mode":
                out.append("3")
            elif cmd.startswith("dumpsys telephony.registry | grep -m1 mData"):
                out.append("    mDataConnectionState=2")
            elif cmd.startswith("dumpsys thermalservice"):
                out.append("Thermal Status: 1")
            else:
                out.append("null")
        return "".join("@@miunlock@@\n" + o + "\n" for o in out)


class PhoneDetailsTests(unittest.TestCase):
    def sections(self, phone):
        return {title: dict(rows) for title, rows in details.phone_details(phone)}

    def test_imei_from_xiaomi_property(self):
        s = self.sections(FakePhone({"ro.ril.miui.imei0": GOOD_IMEI, "ro.serialno": "6a81a217"}))
        self.assertEqual(s["Identity"]["IMEI 1"], GOOD_IMEI)
        self.assertNotIn("Serial number", s["Identity"])  # same as the one in the basic details
        self.assertEqual(s["Identity"]["Wi-Fi address"], "a4:50:46:11:22:33")
        self.assertEqual(s["Battery"]["Charge"], "50%")
        self.assertEqual(s["Connectivity and state"]["Up for"], "2.0 hours")

    def test_modem_sim_board_and_servicing_sections(self):
        props = {"gsm.version.baseband": "M2101-1.0", "gsm.current.phone-type": "1", "gsm.operator.alpha": "Jio",
                 "gsm.operator.numeric": "405874", "gsm.operator.isroaming": "false", "gsm.sim.state": "READY",
                 "gsm.sim.operator.alpha": "Jio", "ro.soc.manufacturer": "Qualcomm", "ro.soc.model": "SM7125",
                 "ro.debuggable": "0", "ro.secure": "1", "ro.build.tags": "release-keys", "sys.boot_completed": "1"}
        s = self.sections(FakePhone(props))
        self.assertEqual(s["Modem and telecom"]["Modem (baseband) version"], "M2101-1.0")
        self.assertEqual(s["Modem and telecom"]["Phone type"], "GSM (2G, 3G, 4G)")     # a code, in words
        self.assertEqual(s["Modem and telecom"]["Roaming"], "No")
        self.assertEqual(s["SIM card"]["SIM state"], "READY")
        self.assertEqual(s["Hardware"]["Chip model"], "SM7125")
        self.assertEqual(s["Servicing and debugging"]["Debuggable build"], "No")
        self.assertEqual(s["Servicing and debugging"]["Secure build (adb root blocked)"], "Yes")
        self.assertEqual(s["Boot"]["Boot finished"], "Yes")

    def test_connectivity_partitions_and_boot_line(self):
        s = self.sections(FakePhone({}))
        conn = s["Connectivity and state"]
        self.assertEqual((conn["Airplane mode"], conn["Wi-Fi"], conn["Location"]), ("Off", "On", "High accuracy"))
        self.assertEqual(conn["Mobile data link"], "Connected")
        self.assertEqual(s["Partitions"]["/data"], "42G of 45G used (94%)")
        self.assertEqual(list(s["Partitions"]), ["/data", "/vendor"])             # the main ones, once each, in order
        self.assertEqual(s["Boot"]["Baseband (kernel line)"], "msm")
        self.assertEqual(s["Battery"]["Heat throttling"], "Light")

    def test_cmdline_and_partition_parsers(self):
        self.assertEqual(details.parse_cmdline("a=1 b c=3=4"), {"a": "1", "c": "3=4"})
        self.assertEqual(details.parse_partitions("nothing useful"), [])

    def test_imei_from_service_call(self):
        s = self.sections(FakePhone({}, parcel(GOOD_IMEI)))
        self.assertEqual(s["Identity"]["IMEI 1"], GOOD_IMEI)

    def test_noise_is_not_an_imei(self):
        s = self.sections(FakePhone({}, parcel("356831091234566")))  # fails the check digit
        self.assertNotIn("IMEI 1", s["Identity"])
        self.assertIn("*#06#", s["Identity"]["IMEI"])

    def test_junk_values_are_dropped(self):
        s = self.sections(FakePhone({"ro.boot.hwc": "unknown", "ro.hardware": "qcom"}))
        self.assertNotIn("Hardware region code", s["Identity"])
        self.assertEqual(s["Hardware"]["Hardware"], "qcom")

    def test_as_text(self):
        text = details.as_text([("A", [("x", "1")]), ("B", [("y", "2")])])
        self.assertEqual(text, "[A]\nx: 1\n\n[B]\ny: 2")


if __name__ == "__main__":
    unittest.main()


class HardwareHelperTests(unittest.TestCase):
    def test_opengl_version(self):
        self.assertEqual(details.opengl_version("196610"), "3.2")
        self.assertIsNone(details.opengl_version(None))

    def test_storage_type(self):
        self.assertEqual(details.storage_type("1d84000.ufshc"), "UFS")
        self.assertEqual(details.storage_type("7824900.sdhci"), "eMMC")
        self.assertIsNone(details.storage_type(""))

    def test_features(self):
        text = "feature:android.hardware.nfc\nfeature:android.hardware.consumerir\nfeature:other.thing=1\n"
        self.assertEqual(details.parse_features(text), ["NFC", "IR blaster"])

    def test_battery_wear(self):
        self.assertEqual(details.battery_wear("4600000", "5000000"), (4600, 5000, 92))
        self.assertEqual(details.battery_wear("4600", "5000"), (4600, 5000, 92))
        self.assertIsNone(details.battery_wear("", "5000"))
        self.assertIsNone(details.battery_wear("9000", "5000"))   # nonsense: more than the design capacity


class MoreSectionsTests(unittest.TestCase):
    def test_xiaomi_and_hardware_sections_when_available(self):
        props = {"ro.product.manufacturer": "Xiaomi", "ro.miui.ui.version.name": "V140", "ro.miui.region": "IN",
                 "ro.product.mod_device": "gram_in_global", "ro.opengles.version": "196610",
                 "ro.boot.bootdevice": "1d84000.ufshc"}
        s = {t: dict(r) for t, r in details.phone_details(FakePhone(props))}
        self.assertEqual(s["Xiaomi / HyperOS"]["Region"], "IN")
        self.assertEqual(s["Xiaomi / HyperOS"]["Model code"], "gram_in_global")
        self.assertEqual(s["Hardware"]["Graphics (OpenGL ES)"], "3.2")
        self.assertEqual(s["Hardware"]["Storage type"], "UFS")

    def test_no_xiaomi_section_on_other_phones(self):
        s = {t for t, _r in details.phone_details(FakePhone({"ro.product.manufacturer": "Google"}))}
        self.assertNotIn("Xiaomi / HyperOS", s)


class SensorTests(unittest.TestCase):
    def test_sensor_list(self):
        text = ("0x00000001) bmi160 Accelerometer | Bosch | ver: 1 | type: android.sensor.accelerometer(1) | perm: n/a\n"
                "0x00000002) bmi160 Accelerometer Wakeup | Bosch | ver: 1 | type: android.sensor.accelerometer(1)\n"
                "0x00000003) tcs3701 Light | AMS | ver: 1 | type: android.sensor.light(5) | perm: n/a\n"
                "not a sensor line\n")
        rows = details.parse_sensors(text)
        self.assertEqual(rows, [("Accelerometer", "bmi160 Accelerometer (Bosch)"), ("Light", "tcs3701 Light (AMS)")])

    def test_gpu_renderer(self):
        rows = dict(details.parse_gpu_renderer("GLES: Qualcomm, Adreno (TM) 618, OpenGL ES 3.2 V@0502.0 (GIT@abc)"))
        self.assertEqual(rows["GPU"], "Adreno (TM) 618")
        self.assertEqual(rows["GPU maker"], "Qualcomm")
        self.assertEqual(details.parse_gpu_renderer("nothing"), [])


class LogViewerTests(unittest.TestCase):
    def test_parse_and_filter(self):
        from miunlock.ui import log_dialog
        text = ("--------- beginning of main\n"
                "11-15 13:20:01.123  1000  1001 I ActivityManager: Start proc com.example\n"
                "11-15 13:20:02.456  1000  1002 W WifiService: slow scan\n"
                "11-15 13:20:03.789  2000  2001 E AndroidRuntime: FATAL EXCEPTION: main\n")
        rows = log_dialog.parse_log(text)
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[1], ("11-15 13:20:01.123", "I", "ActivityManager", "Start proc com.example"))
        self.assertEqual(rows[0][1:], ("V", "", "--------- beginning of main"))
        self.assertEqual(len([r for r in rows if log_dialog.keep(r, "W", "")]), 3)    # header, warning, error
        self.assertEqual(len([r for r in rows if log_dialog.keep(r, "V", "exception")]), 1)
        self.assertEqual(len([r for r in rows if log_dialog.keep(r, "E", "")]), 2)    # header kept, error

    def test_adb_log_and_reboot_arguments_are_checked(self):
        from miunlock import adb

        class Dev:
            serial = "X"
            state = "device"

            def __init__(self):
                self.calls = []

            def shell(self, command, timeout_ms=60000):
                self.calls.append(command)
                return "log"

            def reboot(self, mode=""):
                self.calls.append("reboot:" + mode)

        phone = adb.Phone.__new__(adb.Phone)
        phone._dev, phone.serial = Dev(), "X"
        self.assertEqual(phone.logcat(10), "log")
        self.assertIn("-t 50", phone._dev.calls[0])                  # asks for at least 50 lines
        phone.reboot("recovery")
        self.assertEqual(phone._dev.calls[-1], "reboot:recovery")
        with self.assertRaises(adb.AdbError):
            phone.reboot("sideload; rm -rf /")                       # only known modes go through
