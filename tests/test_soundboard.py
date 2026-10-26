import gc
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from app.palette import ThemeMode
from app.services.soundboard_audio import AudioDriver, SoundboardAudio
from app.services.soundboard_store import SoundboardStore
from app.tools.gaming_soundboard import SoundboardTool, register
from app.tool_registry import ToolRegistry


def wait_for(predicate, timeout=3):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("작업 시간 초과")


class FakeDriver:
    def __init__(self):
        self.started = []
        self.stopped = []
        self.samples = []
        self.active = {}
        self.overlap = False
        self.finish = threading.Event()

    def devices(self):
        return [{"id": "physical", "name": "스피커", "channels": 2}, {"id": "virtual", "name": "가상 장치", "channels": 1}]

    def validate(self, path):
        if Path(path).read_bytes() == b"bad":
            raise ValueError("손상된 오디오")

    def play(self, path, output, ready, start, cancel, gain):
        identity = output["id"]
        if identity == "missing":
            raise OSError("연결 해제")
        ready.set()
        start.wait(1)
        if cancel.is_set():
            return
        if self.active.get(identity):
            self.overlap = True
        self.active[identity] = True
        self.started.append((identity, str(path), time.monotonic()))
        try:
            while not cancel.wait(.005) and not self.finish.is_set():
                self.samples.append((identity, gain(identity)))
        finally:
            self.active[identity] = False
            self.stopped.append(identity)


OUTPUTS = [{"id": "physical", "name": "스피커", "volume": 50}, {"id": "virtual", "name": "가상 장치", "volume": 80}]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = SoundboardStore(self.root / "user_data")
        self.source = self.root / "same.wav"
        self.source.write_bytes(b"valid")
        self.driver = FakeDriver()
        self.identity = self.store.add()

    def tearDown(self):
        self.temp.cleanup()

    def test_registration_restart_original_deleted_and_order(self):
        relative = self.store.register_file(self.identity, self.source, self.driver.validate)
        second = self.store.add()
        self.store.rename(self.identity, "테스트 제목")
        self.store.reorder([second, self.identity])
        self.store.save_settings(42, OUTPUTS)
        self.source.unlink()
        reopened = SoundboardStore(self.store.root)
        self.assertEqual([i["id"] for i in reopened.items()], [second, self.identity])
        self.assertEqual(reopened.items()[1]["title"], "테스트 제목")
        self.assertEqual(reopened.resolve(relative).read_bytes(), b"valid")
        self.assertFalse(Path(relative).is_absolute())
        self.assertEqual(reopened.settings(), (42, OUTPUTS))

    def test_same_name_replacement_and_delete_cleanup(self):
        first = self.store.register_file(self.identity, self.source, self.driver.validate)
        second = self.store.register_file(self.identity, self.source, self.driver.validate)
        self.assertNotEqual(first, second)
        self.assertFalse(self.store.resolve(first).exists())
        self.store.delete(self.identity)
        self.assertFalse(self.store.resolve(second).exists())

    def test_shared_file_not_deleted_until_last_reference(self):
        relative = self.store.register_file(self.identity, self.source, self.driver.validate)
        other = self.store.add()
        with self.store.connect() as db:
            db.execute("UPDATE sounds SET path=? WHERE id=?", (relative, other))
        self.store.delete(self.identity)
        self.assertTrue(self.store.resolve(relative).exists())
        self.store.delete(other)
        self.assertFalse(self.store.resolve(relative).exists())

    def test_invalid_copy_does_not_replace_valid_sound(self):
        first = self.store.register_file(self.identity, self.source, self.driver.validate)
        self.source.write_bytes(b"bad")
        with self.assertRaises(ValueError):
            self.store.register_file(self.identity, self.source, self.driver.validate)
        self.assertEqual(self.store.items()[0]["path"], first)
        self.assertEqual(len(list(self.store.folder.glob("*.wav"))), 1)
        self.assertFalse(list(self.store.folder.glob("*.tmp")))

    def test_db_failure_rolls_back_copy(self):
        with patch.object(self.store, "connect", side_effect=sqlite3.OperationalError("disk full")):
            with self.assertRaises(sqlite3.OperationalError):
                self.store.register_file(self.identity, self.source, self.driver.validate)
        self.assertEqual(self.store.items()[0]["path"], "")
        self.assertFalse(list(self.store.folder.glob("*.wav")))

    def test_copy_failure_leaves_no_registration(self):
        with patch("app.services.soundboard_store.shutil.copyfile", side_effect=OSError("copy failed")):
            with self.assertRaises(OSError):
                self.store.register_file(self.identity, self.source, self.driver.validate)
        self.assertEqual(self.store.items()[0]["path"], "")
        self.assertFalse(list(self.store.folder.glob("*.tmp")))

    def test_deleted_item_registration_leaves_no_file(self):
        self.store.delete(self.identity)
        with self.assertRaises(ValueError):
            self.store.register_file(self.identity, self.source, self.driver.validate)
        self.assertFalse(list(self.store.folder.glob("*.wav")))

    def test_unsafe_paths_cannot_read_or_delete_external_file(self):
        for path in (str(self.source), "../same.wav", "soundboard/../config.json", "soundboard/soundboard.db", ""):
            with self.assertRaises(ValueError):
                self.store.resolve(path)
        with self.store.connect() as db:
            db.execute("UPDATE sounds SET path=? WHERE id=?", (str(self.source), self.identity))
        self.store.delete(self.identity)
        self.assertTrue(self.source.exists())

    def test_duplicate_devices_bad_volume_rejected(self):
        for outputs in ([], [OUTPUTS[0]] * 2, OUTPUTS + [OUTPUTS[0]], [{"id": "a", "name": "a", "volume": float("nan")}], [None]):
            with self.assertRaises(ValueError):
                self.store.save_settings(100, outputs)
        self.assertEqual(self.store.settings(), (100, []))

    def test_corrupted_settings_and_atomic_reorder(self):
        with self.store.connect() as db:
            db.executemany("INSERT INTO settings VALUES (?,?)", [("volume", "NaN"), ("outputs", "[null]")])
        self.assertEqual(self.store.settings(), (100, []))
        with self.assertRaises(ValueError):
            self.store.reorder([self.identity, self.identity])
        self.assertEqual(len(self.store.items()), 1)


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.driver = FakeDriver()
        self.audio = SoundboardAudio(self.driver)
        self.audio.volumes(50, OUTPUTS)

    def tearDown(self):
        self.audio.close()
        self.audio.worker.join(2)
        self.assertFalse(self.audio.worker.is_alive())

    def test_dual_output_start_and_toggle_stops_both(self):
        self.audio.toggle("a", "a.wav", OUTPUTS)
        wait_for(lambda: len(self.driver.started) == 2)
        self.assertLess(abs(self.driver.started[0][2] - self.driver.started[1][2]), .1)
        self.audio.toggle("a", "a.wav", OUTPUTS)
        wait_for(lambda: len(self.driver.stopped) == 2)
        self.assertIsNone(self.audio.current)

    def test_switch_and_rapid_clicks_do_not_overlap(self):
        self.audio.toggle("a", "a.wav", OUTPUTS)
        wait_for(lambda: len(self.driver.started) == 2)
        for i in range(30):
            self.audio.toggle(str(i), str(i), OUTPUTS)
        wait_for(lambda: any(path == "29" for _, path, _ in self.driver.started))
        self.assertFalse(self.driver.overlap)
        self.assertEqual(self.audio.current, "29")

    def test_live_master_times_independent_gain(self):
        self.audio.toggle("a", "a.wav", OUTPUTS)
        wait_for(lambda: ("physical", .25) in self.driver.samples and ("virtual", .4) in self.driver.samples)
        self.audio.volumes(20, [OUTPUTS[0], dict(OUTPUTS[1], volume=0)])
        wait_for(lambda: ("physical", .1) in self.driver.samples and ("virtual", 0) in self.driver.samples)

    def test_one_device_failure_keeps_other_playing(self):
        self.audio.toggle("a", "a.wav", [OUTPUTS[0], dict(OUTPUTS[1], id="missing")])
        wait_for(lambda: len(self.driver.started) == 1 and not self.audio.events.empty())
        self.assertTrue(self.driver.active["physical"])
        self.assertEqual(self.audio.current, "a")

    def test_eof_clears_state_and_close_releases_streams(self):
        self.audio.toggle("a", "a.wav", OUTPUTS)
        wait_for(lambda: len(self.driver.started) == 2)
        self.driver.finish.set()
        wait_for(lambda: self.audio.current is None)
        self.assertEqual(len(self.driver.stopped), 2)


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = SoundboardStore(self.temp.name)
        self.root = tk.Tk()
        self.root.geometry("850x700")
        self.driver = FakeDriver()
        self.tool = SoundboardTool(self.root, SimpleNamespace(dark_mode=ThemeMode("dark")), self.store, SoundboardAudio(self.driver))
        self.tool.pack(fill="both", expand=True)
        self.root.update()

    def tearDown(self):
        self.tool.destroy()
        self.root.destroy()
        self.tool.audio.worker.join(2)
        gc.collect()
        self.temp.cleanup()

    def pump(self, seconds=.12):
        end = time.monotonic()+seconds
        while time.monotonic() < end:
            self.root.update()
            time.sleep(.005)

    def test_edit_register_title_reorder_delete_and_exit(self):
        self.tool.toggle_edit()
        self.tool.add()
        self.tool.add()
        self.root.update()
        first = self.tool.items[0]["id"]
        self.tool.entries[first].delete(0, "end")
        self.tool.entries[first].insert(0, "새 제목")
        self.tool.move(0, 1)
        self.assertEqual(self.store.items()[1]["title"], "새 제목")
        self.tool.delete(first)
        self.tool.toggle_edit()
        self.assertFalse(self.tool.entries)
        self.assertFalse(self.tool.edit_actions.winfo_ismapped())
        self.assertEqual(str(self.tool.selectors[0].cget("state")), "disabled")

    def test_edit_mode_click_never_plays_and_cancel_keeps_file(self):
        self.tool.toggle_edit()
        self.tool.add()
        with patch("app.tools.gaming_soundboard.filedialog.askopenfilename", return_value="") as dialog:
            self.tool.click(self.tool.items[0]["id"])
        dialog.assert_called_once()
        self.assertFalse(self.driver.started)

    def test_empty_missing_file_and_disconnected_device_are_contained(self):
        self.tool.toggle_edit()
        self.tool.add()
        identity = self.tool.items[0]["id"]
        self.tool.toggle_edit()
        self.tool.click(identity)
        self.assertIn("오디오 파일", self.tool.status.get())
        self.tool.outputs = [dict(OUTPUTS[0], id="missing")]
        self.tool.devices = self.driver.devices()
        self.tool.update_selectors()
        self.assertIn("연결되지 않은", self.tool.status.get())

    def test_two_device_selection_rejects_duplicate_and_restores_volume(self):
        self.pump()
        self.tool.toggle_edit()
        self.tool.selectors[0].current(1)
        self.tool.select_outputs()
        self.tool.selectors[1].current(2)
        self.tool.select_outputs()
        self.assertEqual(len(self.store.settings()[1]), 2)
        self.tool.selectors[1].current(1)
        self.tool.select_outputs()
        self.assertEqual(len({o["id"] for o in self.tool.outputs}), 2)
        self.tool.change_device(0, "23")
        self.tool.change_master("41")
        self.assertEqual(self.store.settings()[0], 41)
        self.assertEqual(self.store.settings()[1][0]["volume"], 23)

    def test_responsive_grid_and_three_themes_registration(self):
        registry = ToolRegistry()
        register(registry)
        self.assertEqual(registry.tools_for("게임")[0].id, "gaming.soundboard")
        self.tool.toggle_edit()
        for _ in range(8):
            self.tool.add()
        self.pump()
        wide = self.tool.columns
        self.root.geometry("450x700")
        self.pump()
        self.assertLess(self.tool.columns, wide)
        self.assertGreater(self.tool.canvas.bbox("all")[3], self.tool.canvas.winfo_height())
        for theme in ("light", "green"):
            tool = SoundboardTool(self.root, SimpleNamespace(dark_mode=ThemeMode(theme)), self.store, SoundboardAudio(self.driver))
            tool.pack()
            self.root.update()
            tool.destroy()
            tool.audio.worker.join(2)


if __name__ == "__main__":
    unittest.main()
