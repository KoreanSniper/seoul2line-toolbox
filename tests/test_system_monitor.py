import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.tools import system_monitor as monitor


class SystemMonitorTests(unittest.TestCase):
    def sampler(self):
        return SimpleNamespace(cpu_snapshot=lambda: "25%", gpu_snapshot=lambda: ("30%", "200/4000 MB"),
                               net_snapshot=lambda: "측정 중")

    def test_snapshot_reads_real_memory_and_disk_without_missing_import(self):
        data = monitor.SystemMonitor.snapshot(self.sampler())
        self.assertEqual(set(data), {"CPU", "RAM", "GPU", "VRAM", "디스크", "네트워크"})
        self.assertEqual(data["CPU"], "25%")
        self.assertIn("GB", data["RAM"])
        self.assertIn("GB", data["디스크"])

    def test_disk_access_failure_does_not_break_other_cards(self):
        with patch.object(monitor.shutil, "disk_usage", side_effect=OSError("unavailable")):
            data = monitor.SystemMonitor.snapshot(self.sampler())
        self.assertEqual(data["디스크"], "확인 불가")
        self.assertEqual(data["CPU"], "25%")
        self.assertIn("GB", data["RAM"])

    def test_open_refresh_close_and_reopen_cancel_pending_callbacks(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        with patch.object(monitor.SystemMonitor, "gpu_snapshot", return_value=("30%", "200/4000 MB")), patch.object(monitor.SystemMonitor, "cpu_snapshot", return_value="25%"), patch.object(monitor.SystemMonitor, "net_snapshot", return_value="측정 중"):
            for _ in range(2):
                view = monitor.SystemMonitor(root, SimpleNamespace(dark_mode=True))
                self.assertIn("GB", view.labels["디스크"].cget("text"))
                previous = view._refresh_job
                view.refresh()
                pending = root.tk.splitlist(root.tk.call("after", "info"))
                self.assertNotIn(previous, pending)
                current = view._refresh_job
                view.destroy()
                self.assertNotIn(current, root.tk.splitlist(root.tk.call("after", "info")))
                root.update_idletasks()


if __name__ == "__main__":
    unittest.main()
