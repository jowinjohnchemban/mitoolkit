"""Live status window: tabs, one scrollbar per page, process list, gauges and legend, no crashes."""
import os
import sys
import tkinter as tk
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))

from test_monitor import TOP, FakePhone  # noqa: E402
from tkhelper import make_root  # noqa: E402

try:
    _r = tk.Tk()
    _r.destroy()
    HAVE_DISPLAY = True
except tk.TclError:
    HAVE_DISPLAY = False


class _Phone(FakePhone):
    def shell(self, command, timeout_ms=0):
        if command.startswith("top"):
            return TOP
        self.n += 1
        busy = 100 * self.n
        lines = "\n".join(f"{name}  {busy + k} 0 0 {1000 * self.n - busy - k} 0 0 0 0"
                          for k, name in enumerate(("cpu", "cpu0", "cpu1")))
        parts = [lines, "MemTotal: 4194304 kB\nMemAvailable: 1048576 kB", "  level: 80\n  status: 2\n", "-450000", "",
                 "1800000\n1100000", "cpu 41000\nbattery 30000\nGPU 52000", "/dev/x 47185920 44150000 3 94% /data",
                 "2400000\n1800000", "37", "490000000", "840000000", "", ""]
        return "".join("@@m@@\n" + p + "\n" for p in parts)


@unittest.skipUnless(HAVE_DISPLAY, "needs a display")
class LiveDialogTests(unittest.TestCase):
    def setUp(self):
        from mitoolkit import gui
        self.root = make_root()
        self.app = gui.App(self.root)
        self.app.android = {"serial": "X", "state": "device", "model": "POCO M2 Pro"}
        self.root.update()
        phone = _Phone()
        from mitoolkit.ui.live_dialog import LiveStatusDialog
        self.dlg = LiveStatusDialog(self.app, "X", "POCO M2 Pro", start=False)   # no reading thread: we feed readings
        from mitoolkit import monitor
        self.mon = monitor.Monitor(phone)

    def tearDown(self):
        self.dlg.close()
        self.root.destroy()

    def feed(self, count=3):
        for _ in range(count):
            self.dlg._update(self.mon.sample(), None)
        self.root.update()

    def test_an_unplugged_phone_is_shown_at_once_and_the_bar_stays_quiet_while_live(self):
        d = self.dlg
        self.feed(2)
        sub = d.sub.cget("text")
        self.feed(2)
        self.assertEqual(d.sub.cget("text"), sub)                 # repeated readings do not rewrite the bar
        self.assertNotIn("Updated", sub)
        self.app.android = None                                   # the main window noticed it is gone
        d._watch_connection()
        self.assertEqual(d.live.cget("text"), "● Disconnected")
        d._update(None, "device offline")                         # a failing read does not overwrite that
        self.assertEqual(d.live.cget("text"), "● Disconnected")
        self.app.android = {"serial": "X", "state": "device"}
        d._watch_connection()
        self.assertEqual(d.live.cget("text"), "◌ Reconnecting")

    def test_samples_fill_gauges_cores_sensors_and_processes(self):
        self.feed(4)
        d = self.dlg
        self.assertEqual(d.g_gpu.state_text, "Normal")           # GPU gauge appeared with its word
        self.assertIn(d.g_gpu, d._gauge_order)
        self.assertEqual(len(d.core_cells), 2)
        self.assertEqual(d.live.cget("text"), "● Live")
        # the lists are built when their tab opens, from the latest reading
        self.assertFalse(d.sensor_tree.get_children())
        d.tab_var.set("sensors")
        d._show_tab()
        self.assertTrue(d.sensor_tree.get_children())
        d.tab_var.set("processes")
        d._show_tab()
        self.assertIn("com.example.video", [d.proc_tree.item(i)["values"][0] for i in d.proc_tree.get_children()])

    def test_readings_that_arrive_together_are_all_graphed_but_shown_once(self):
        d = self.dlg
        before = len(d.cpu.data[0])
        for _ in range(5):
            d._deliver(self.mon.sample(), None)
        self.assertTrue(d._scheduled)                      # one task for the whole batch
        self.assertEqual(self.app.q.qsize(), 1)
        queued = len(d._inbox)                             # (the real reading thread may have added one)
        self.assertGreaterEqual(queued, 5)
        d._drain()                                         # what the window's pump does with that task
        self.assertEqual(len(d.cpu.data[0]) - before, queued)  # every reading reached the graph
        self.assertFalse(d._scheduled)

    def test_a_broken_reading_does_not_break_the_window(self):
        d = self.dlg
        d._deliver({"cpu": "not a number", "mem_pct": None, "thermal": "oops"}, None)
        d._drain()
        self.root.update()
        self.assertTrue(d.alive())

    def test_tabs_swap_pages_and_only_the_graph_pages_scroll(self):
        d = self.dlg
        for name in ("processor", "sensors", "processes", "overview"):
            d.tab_var.set(name)
            d._show_tab()
            self.root.update()
            self.assertEqual([k for k, p in d.pages.items() if p.winfo_manager()], [name])
        self.assertEqual(set(d.scrolls), {"overview", "processor"})     # lists never sit inside a scrolling page

    def test_time_range_shows_only_on_the_graphs_tab(self):
        d = self.dlg
        d.tab_var.set("processes")
        d._show_tab()
        self.assertFalse(d.range_box.winfo_manager())
        d.tab_var.set("overview")
        d._show_tab()
        self.assertTrue(d.range_box.winfo_manager())

    def test_process_filter_sort_and_search(self):
        self.feed(3)
        d = self.dlg
        d.tab_var.set("processes")
        d._show_tab()
        names = lambda: [d.proc_tree.item(i)["values"][0] for i in d.proc_tree.get_children()]  # noqa: E731
        self.assertEqual(names(), ["com.example.video"])                 # apps only
        d.filter_var.set("apps+system")
        d._fill_procs()
        self.assertIn("system_server", names())
        d.query.set("system")
        self.root.update()
        self.assertEqual(names(), ["system_server"])
        d._sort_by("name")
        self.assertEqual(d.sort_key, "name")

    def test_time_range_changes_every_graph_and_goes_up_to_an_hour(self):
        d = self.dlg
        d.window_var.set(3600)
        d._window_changed()
        self.assertTrue(all(c.window == 3600 for c in d.charts))
        self.assertEqual(d.charts[0].data[0].maxlen, 3600)

    def test_pause_and_no_answer_states(self):
        d = self.dlg
        d._toggle_pause()
        self.assertIn("Paused", d.live.cget("text"))
        d._toggle_pause()
        d._update(None, "boom")
        self.assertIn("No answer", d.live.cget("text"))

    def test_gauge_levels_use_a_word_as_well_as_colour(self):
        from mitoolkit.ui.components.charts import Gauge
        g = Gauge(self.root, "Memory", self.dlg.fonts, (75, 90))
        self.assertEqual(g.level(50)[1], "Normal")
        self.assertEqual(g.level(80)[1], "High")
        self.assertEqual(g.level(95)[1], "Critical")
        battery = Gauge(self.root, "Battery", self.dlg.fonts, (40, 20), invert=True)
        self.assertEqual(battery.level(15)[1], "Critical")
        self.assertEqual(battery.level(30)[1], "Low")
        self.assertEqual(battery.level(80)[1], "Normal")

    def test_legend_reports_last_min_avg_max(self):
        d = self.dlg
        for v in (10, 20, 30):
            d.cpu.push(v)
        st = d.cpu.stats(0)
        self.assertEqual((st["last"], st["min"], st["avg"], st["max"]), (30, 10, 20, 30))


if __name__ == "__main__":
    unittest.main()
