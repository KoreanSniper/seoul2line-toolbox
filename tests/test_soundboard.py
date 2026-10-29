import gc
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
import wave
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

    def validate(self, path, cancel=None):
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
        with patch("pathlib.Path.open", side_effect=OSError("copy failed")):
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

    def test_registration_cancelled_during_validation_keeps_old_file(self):
        old = self.store.register_file(self.identity, self.source, self.driver.validate)
        cancelled = threading.Event()
        def validate(path):
            cancelled.set()
        with self.assertRaisesRegex(ValueError, "취소"):
            self.store.register_file(self.identity, self.source, validate, cancelled)
        self.assertEqual(self.store.items()[0]["path"], old)
        self.assertEqual(len(list(self.store.folder.glob("*.wav"))), 1)

    def test_cleanup_never_deletes_non_owned_filename(self):
        path = self.store.folder / "user-song.wav"
        path.write_bytes(b"user")
        with self.store.connect() as db:
            db.execute("UPDATE sounds SET path=? WHERE id=?", (path.relative_to(self.store.root).as_posix(), self.identity))
        self.store.delete(self.identity)
        self.assertEqual(path.read_bytes(), b"user")

    def test_real_decoder_validates_temporary_copy_and_survives_original_removal(self):
        with wave.open(str(self.source), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(22050)
            audio.writeframes(b"\0\0" * 2205)
        driver = AudioDriver()
        relative = self.store.register_file(self.identity, self.source, driver.validate)
        self.source.unlink()
        driver.validate(self.store.resolve(relative))


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

    def test_all_endpoints_fail_no_default_fallback(self):
        self.audio.toggle("a", "a.wav", [dict(OUTPUTS[0], id="missing")])
        wait_for(lambda: self.audio.current is None)
        self.assertFalse(self.driver.started)
        errors = []
        while not self.audio.events.empty():
            event = self.audio.events.get_nowait()
            if event[1] == "error":
                errors.append(event)
        self.assertEqual(len(errors), 1)

    def test_real_decoder_missing_and_corrupt_playback_are_contained(self):
        self.audio.close()
        self.audio.worker.join(2)
        self.audio = SoundboardAudio(AudioDriver())
        speaker = SimpleNamespace(id="physical", channels=2)
        with tempfile.TemporaryDirectory() as folder:
            corrupt = Path(folder) / "corrupt.wav"
            corrupt.write_bytes(b"corrupt")
            with patch.dict(sys.modules, {"soundcard": SimpleNamespace(all_speakers=lambda: [speaker])}):
                for path in (Path(folder) / "missing.wav", corrupt):
                    self.audio.toggle(str(path), path, [OUTPUTS[0]])
                    wait_for(lambda: self.audio.current is None)
                    events = []
                    while not self.audio.events.empty():
                        events.append(self.audio.events.get_nowait())
                    self.assertTrue(any(e[1] == "error" for e in events))


class UITests(unittest.TestCase):
    def prepare_delayed(self):
        source = Path(self.temp.name) / "delay.wav"
        source.write_bytes(b"valid")
        identities = [self.store.add(), self.store.add()]
        for identity in identities:
            self.store.register_file(identity, source, self.driver.validate)
        self.tool.outputs = [dict(OUTPUTS[0])]
        self.tool.reload()
        self.tool.delay.set("0.2")
        return identities

    def test_delayed_play_waits_then_starts(self):
        first, _ = self.prepare_delayed()
        self.tool.click(first)
        self.assertIsNone(self.tool.audio.current)
        self.assertEqual(self.tool.pending, first)
        self.pump(.08)
        self.assertFalse(self.driver.started)
        self.pump(.3)
        self.assertEqual(self.tool.audio.current, first)
        wait_for(lambda: bool(self.driver.started))
        self.assertTrue(self.driver.started)
        self.assertIsNone(self.tool.pending)

    def test_delayed_reclick_replace_stop_edit_and_destroy_cancel(self):
        first, second = self.prepare_delayed()
        self.tool.click(first)
        self.tool.click(first)
        self.assertIsNone(self.tool.pending)
        self.tool.click(first)
        self.tool.click(second)
        self.assertEqual(self.tool.pending, second)
        self.tool.stop()
        self.pump(.25)
        self.assertFalse(self.driver.started)
        self.tool.click(first)
        self.tool.toggle_edit()
        self.assertIsNone(self.tool.pending)
        self.tool.toggle_edit()
        self.tool.click(first)
        timer = self.tool.play_timer
        self.tool.destroy()
        self.assertNotIn(timer, self.root.tk.call("after", "info"))
        self.assertIsNone(self.tool.pending)

    def test_delay_invalid_values_and_file_removed_while_waiting(self):
        first, _ = self.prepare_delayed()
        for value in ("NaN", "inf", "-1", "3601", "abc"):
            self.tool.delay.set(value)
            self.tool.click(first)
            self.assertIsNone(self.tool.pending)
            self.assertIsNone(self.tool.audio.current)
        self.tool.delay.set("0.1")
        self.tool.click(first)
        self.store.resolve(self.tool.items[0]["path"]).unlink()
        self.pump(.2)
        self.assertIn("파일이 없습니다", self.tool.status.get())
        self.assertFalse(self.driver.started)

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
        self.tool.executor.shutdown(wait=True)
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

    def test_normal_mode_device_volume_highlight_eof_and_edit_stops(self):
        source = Path(self.temp.name) / "source.wav"
        source.write_bytes(b"valid")
        identity = self.store.add()
        self.store.register_file(identity, source, self.driver.validate)
        self.tool.outputs = [dict(o) for o in OUTPUTS]
        self.tool.audio.volumes(100, self.tool.outputs)
        self.tool.reload()
        self.tool.click(identity)
        self.pump()
        self.assertTrue(self.tool.buttons[identity].active)
        self.tool.device_scales[0].set(23)
        self.pump()
        self.assertFalse(self.tool.editing)
        wait_for(lambda: ("physical", .23) in self.driver.samples)
        self.assertIn(("physical", .23), self.driver.samples)
        self.assertEqual(self.store.settings()[1][0]["volume"], 23)
        self.driver.finish.set()
        self.pump()
        self.assertFalse(self.tool.buttons[identity].active)
        self.driver.finish.clear()
        self.tool.click(identity)
        self.pump()
        self.tool.toggle_edit()
        self.pump()
        self.assertIsNone(self.tool.audio.current)
        self.assertFalse(any(self.driver.active.values()))

    def test_missing_or_corrupt_file_error_does_not_break_ui(self):
        actual = AudioDriver()
        source = Path(self.temp.name) / "corrupt.wav"
        source.write_bytes(b"corrupt")
        with self.assertRaises(Exception):
            actual.validate(source)
        with self.assertRaises(Exception):
            actual.validate(source.with_name("missing.wav"))
        identity = self.store.add()
        self.tool.reload()
        self.tool.click(identity)
        self.assertIsNone(self.tool.audio.current)
        self.tool.toggle_edit()
        self.assertTrue(self.tool.editing)

    def test_renamed_same_name_distinct_ids_and_missing_device_preserved(self):
        self.tool.outputs = [dict(o) for o in OUTPUTS]
        self.tool.devices = [dict(d, name="동일 이름") for d in self.driver.devices()]
        self.tool.update_selectors()
        self.tool.sync_state()
        self.assertIn("동일 이름", self.tool.output_summary.cget("text"))
        self.assertNotEqual(self.tool.selectors[0].get(), self.tool.selectors[1].get())
        self.tool.devices = self.tool.devices[:1]
        self.tool.update_selectors()
        self.assertEqual(self.tool.outputs[1]["id"], "virtual")
        self.assertIn("연결 끊김", self.tool.selectors[1].get())

    def test_close_during_registration_cancels_and_cleans_new_copy(self):
        entered, release = threading.Event(), threading.Event()
        def validating(path, cancel=None):
            entered.set()
            release.wait(2)
            if cancel and cancel.is_set():
                raise ValueError("취소")
        self.driver.validate = validating
        source = Path(self.temp.name) / "source.wav"
        source.write_bytes(b"valid")
        self.tool.toggle_edit()
        self.tool.add()
        identity = self.tool.items[0]["id"]
        with patch("app.tools.gaming_soundboard.filedialog.askopenfilename", return_value=str(source)):
            self.tool.click(identity)
        self.assertTrue(entered.wait(1))
        self.tool.destroy()
        release.set()
        self.tool.executor.shutdown(wait=True)
        self.assertEqual(self.store.items()[0]["path"], "")
        self.assertFalse(list(self.store.folder.glob("*.wav")))
        self.assertFalse(list(self.store.folder.glob("*.tmp")))

    def test_async_file_selection_registers_copied_file(self):
        source = Path(self.temp.name) / "source.wav"
        source.write_bytes(b"valid")
        self.tool.toggle_edit()
        self.tool.add()
        identity = self.tool.items[0]["id"]
        with patch("app.tools.gaming_soundboard.filedialog.askopenfilename", return_value=str(source)):
            self.tool.click(identity)
        deadline = time.monotonic() + 5
        while self.tool.busy and time.monotonic() < deadline:
            self.pump(.02)
        self.assertFalse(self.tool.busy)
        source.unlink()
        self.assertTrue(self.store.resolve(self.store.items()[0]["path"]).exists())


if __name__ == "__main__":
    unittest.main()
