import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.tools import system_monitor as monitor


class SystemMonitorTests(unittest.TestCase):
    def test_cpu_calculates_interval_usage_without_external_commands(self):
        sampler = SimpleNamespace(last_cpu=None)
        with patch.object(monitor, "cpu_times", side_effect=[(100, 200, 100), (160, 260, 140)]), patch.object(monitor.subprocess, "run") as run:
            self.assertEqual(monitor.SystemMonitor.cpu_snapshot(sampler), "측정 중")
            self.assertEqual(monitor.SystemMonitor.cpu_snapshot(sampler), "40%")
        run.assert_not_called()

    def test_cpu_idle_and_fully_busy_intervals(self):
        sampler = SimpleNamespace(last_cpu=(100, 200, 100))
        with patch.object(monitor, "cpu_times", side_effect=[(200, 300, 100), (200, 350, 150)]):
            self.assertEqual(monitor.SystemMonitor.cpu_snapshot(sampler), "0%")
            self.assertEqual(monitor.SystemMonitor.cpu_snapshot(sampler), "100%")

    def test_cpu_restarts_sampling_after_api_failure(self):
        sampler = SimpleNamespace(last_cpu=(100, 200, 100))
        with patch.object(monitor, "cpu_times", side_effect=[OSError("unavailable"), (200, 400, 200), (250, 450, 250)]):
            self.assertEqual(monitor.SystemMonitor.cpu_snapshot(sampler), "확인 불가")
            self.assertIsNone(sampler.last_cpu)
            self.assertEqual(monitor.SystemMonitor.cpu_snapshot(sampler), "측정 중")
            self.assertEqual(monitor.SystemMonitor.cpu_snapshot(sampler), "50%")

    def test_cpu_zero_or_reset_counters_do_not_show_invalid_percentage(self):
        for previous, current in [((100, 200, 100), (100, 200, 100)), ((100, 200, 100), (50, 100, 50))]:
            sampler = SimpleNamespace(last_cpu=previous)
            with patch.object(monitor, "cpu_times", return_value=current):
                self.assertEqual(monitor.SystemMonitor.cpu_snapshot(sampler), "측정 중")
            self.assertEqual(sampler.last_cpu, current)

    def test_windows_cpu_api_reads_64_bit_counters_and_reports_failure(self):
        def get_times(*pointers):
            for index, pointer in enumerate(pointers):
                pointer._obj.dwHighDateTime = index + 1
                pointer._obj.dwLowDateTime = index + 10
            return 1
        api = Mock(side_effect=get_times)
        with patch.object(monitor.ctypes, "WinDLL", return_value=SimpleNamespace(GetSystemTimes=api)):
            self.assertEqual(monitor.cpu_times(), tuple(((index + 1) << 32) | (index + 10) for index in range(3)))
            api.side_effect = None
            api.return_value = 0
            with self.assertRaises(OSError):
                monitor.cpu_times()

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
