import gc
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

import numpy as np
import soundfile as sf
from app.palette import ThemeMode
from app.services.tts import WindowsTTS
from app.services.voice_fx import builtin_presets, default_settings
from app.services.soundboard_store import SoundboardStore
from app.tools.file_tts import TTSTool, register
from app.tool_registry import ToolRegistry


def write_wave(path):
    with wave.open(str(path), "wb") as sound:
        sound.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        sound.writeframes(b"\0\0" * 100)


class TTSTests(unittest.TestCase):
    def test_robot_preserves_duration_channels_and_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            for channels in (1, 2):
                rate = 22050
                signal = .5 * np.sin(2 * np.pi * 440 * np.arange(rate) / rate)
                signal[:100] = 0
                samples = np.repeat(signal[:, None], channels, axis=1)
                target = Path(directory) / "robot.wav"
                engine = WindowsTTS()
                with patch.object(engine, "_run", side_effect=lambda p: sf.write(p["path"], samples, rate, subtype="PCM_16")):
                    engine.generate("로봇", target, effect="robot")
                actual, actual_rate = sf.read(target, always_2d=True)
                self.assertEqual(actual_rate, rate)
                self.assertEqual(actual.shape, samples.shape)
                self.assertLessEqual(np.max(np.abs(actual)), .501)
                np.testing.assert_array_equal(actual[:100], 0)
                self.assertGreater(np.max(np.abs(actual - samples)), .2)
                # 원본 440Hz에 더해 링 변조의 350/530Hz 성분을 확인한다.
                spectrum = np.abs(np.fft.rfft(actual[:, 0]))
                self.assertGreater(spectrum[350], spectrum[440])
                self.assertGreater(spectrum[530], spectrum[440])
                self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_effect_failure_and_late_cancel_preserve_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "voice.wav"
            target.write_bytes(b"original")
            for outcome in ("failure", "cancel"):
                engine = WindowsTTS()
                def effect(source, destination):
                    write_wave(destination)
                    if outcome == "failure":
                        raise OSError("변형 저장 실패")
                    engine.close()
                with patch.object(engine, "_run", side_effect=lambda p: write_wave(p["path"])), patch.object(engine, "_robot_effect", side_effect=effect):
                    with self.assertRaises((OSError, RuntimeError)):
                        engine.generate("테스트", target, effect="robot")
                self.assertEqual(target.read_bytes(), b"original")
                self.assertEqual(list(Path(directory).iterdir()), [target])
            with patch.object(engine, "_run") as run:
                with self.assertRaises(ValueError):
                    engine.generate("테스트", target, effect="unknown")
                run.assert_not_called()

    def test_robot_reaches_one_time_output_and_soundboard(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SoundboardStore(directory)
            engine = WindowsTTS()
            samples = .4 * np.sin(2 * np.pi * 440 * np.arange(22050) / 22050)
            def verify(path, *args):
                actual, rate = sf.read(path)
                self.assertEqual(rate, 22050)
                self.assertGreater(np.max(np.abs(actual - samples)), .2)
            with patch.object(engine, "_run", side_effect=lambda p: sf.write(p["path"], samples, 22050)), patch("app.services.soundboard_store.SoundboardStore", return_value=store), patch("app.services.soundboard_audio.AudioDriver.play", side_effect=verify) as play:
                engine.play_once("로봇", {"id": "cable", "name": "케이블"}, effect="robot")
                play.assert_called_once()
                engine.add_to_soundboard("로봇", "변형 음성", effect="robot")
                verify(store.resolve(store.items()[0]["path"]))

    def test_one_time_output_cleanup_success_failure_and_cancel(self):
        output = {"id": "cable-id", "name": "CABLE Input", "channels": 2}
        for outcome in ("success", "failure", "cancel"):
            with self.subTest(outcome=outcome):
                engine = WindowsTTS()
                paths = []
                def generate(payload):
                    paths.append(Path(payload["path"]).parent)
                    write_wave(payload["path"])
                    if outcome == "cancel":
                        engine.close()
                def play(path, device, ready, start, cancel, gain):
                    self.assertTrue(Path(path).is_file())
                    self.assertEqual(device["id"], "cable-id")
                    self.assertTrue(start.is_set())
                    self.assertEqual(gain("cable-id"), 1)
                    if outcome == "failure":
                        raise OSError("장치 연결 해제")
                with patch.object(engine, "_run", side_effect=generate), patch("app.services.soundboard_audio.AudioDriver.play", side_effect=play) as playing:
                    if outcome == "success":
                        self.assertEqual(engine.play_once("안내", output, volume=25), "CABLE Input")
                    else:
                        with self.assertRaises((OSError, RuntimeError)):
                            engine.play_once("안내", output)
                    self.assertEqual(playing.call_count, 0 if outcome == "cancel" else 1)
                self.assertTrue(paths)
                self.assertTrue(all(not path.exists() for path in paths))

    def test_one_time_close_during_play_releases_file(self):
        engine = WindowsTTS()
        entered = threading.Event()
        paths, errors = [], []
        def play(path, output, ready, start, cancel, gain):
            paths.append(Path(path))
            entered.set()
            if not cancel.wait(3):
                raise AssertionError("종료 취소가 전달되지 않음")
        def run():
            try:
                engine.play_once("종료", {"id": "cable", "name": "케이블"})
            except Exception as exc:
                errors.append(exc)
        with patch.object(engine, "_run", side_effect=lambda p: write_wave(p["path"])), patch("app.services.soundboard_audio.AudioDriver.play", side_effect=play):
            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertTrue(paths[0].exists())
            finally:
                engine.close()
                worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertFalse(errors)
        self.assertFalse(paths[0].parent.exists())

    def test_soundboard_registration_and_failed_copy_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SoundboardStore(directory)
            engine = WindowsTTS()
            with patch("app.services.soundboard_store.SoundboardStore", return_value=store), patch.object(engine, "_run", side_effect=lambda p: write_wave(p["path"])):
                engine.add_to_soundboard("테스트", "제목")
                item = store.items()[0]
                self.assertEqual(item["title"], "제목")
                self.assertTrue(store.resolve(item["path"]).exists())
                with patch.object(store, "register_file", side_effect=OSError("디스크 오류")):
                    with self.assertRaises(OSError):
                        engine.add_to_soundboard("실패", "실패 항목")
                self.assertEqual(store.items(), [item])
                self.assertEqual(len(list(store.folder.glob("*.wav"))), 1)

    def test_validation_and_failed_generation_preserve_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "한글.wav"
            target.write_bytes(b"original")
            engine = WindowsTTS()
            for text, rate, volume in ((" ", 0, 100), ("a" * 10001, 0, 100), ("a", 11, 100), ("a", 0, -1)):
                with self.assertRaises(ValueError):
                    engine.generate(text, target, rate=rate, volume=volume)
            with patch.object(engine, "_run", side_effect=RuntimeError("실패")):
                with self.assertRaises(RuntimeError):
                    engine.generate("테스트", target)
            self.assertEqual(target.read_bytes(), b"original")
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_atomic_success_empty_output_and_cancellation(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "음성.wav"
            engine = WindowsTTS()
            with patch.object(engine, "_run", side_effect=lambda p: write_wave(p["path"])):
                engine.generate("한글 '$()' <speak>일반 텍스트</speak>", target)
            original = target.read_bytes()
            with patch.object(engine, "_run", return_value=""):
                with self.assertRaises((EOFError, wave.Error)):
                    engine.generate("빈 결과", target)
            def cancel(payload):
                write_wave(payload["path"])
                engine.close()
            with patch.object(engine, "_run", side_effect=cancel):
                with self.assertRaises(RuntimeError):
                    engine.generate("취소", target)
            self.assertEqual(target.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [target])


class FakeEngine:
    def __init__(self):
        self.closed = False
        self.calls = []

    def voices(self):
        return [{"name": "English", "culture": "en-US"}, {"name": "한국어", "culture": "ko-KR"}]

    def generate(self, *args):
        self.calls.append(args)
        return args[1]

    def close(self):
        self.closed = True

    def play_once(self, *args):
        self.calls.append(("played", args))
        return args[1]["name"]

    def add_to_soundboard(self, *args):
        self.calls.append(("added", args))
        return args[1]


class TTSUITests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        for module in ("app.services.voice_fx", "app.services.voice_fx_store", "app.services.voice_fx_log"):
            patcher = patch(module + ".data_directory", return_value=Path(self.temporary.name))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.devices = [{"id": "cable", "name": "케이블", "channels": 2}]
        self.device_patch = patch("app.tools.file_tts.AudioDriver.devices", side_effect=lambda: list(self.devices))
        self.device_patch.start()
        self.addCleanup(self.device_patch.stop)

    def test_close_during_soundboard_registration_cleans_pending_item(self):
        with tempfile.TemporaryDirectory() as directory:
            store = SoundboardStore(directory)
            engine = WindowsTTS()
            entered = threading.Event()
            def validate(path, cancel=None):
                entered.set()
                if not cancel.wait(3):
                    raise AssertionError("창 종료 시 등록 취소가 전달되지 않음")
            root = tk.Tk()
            tool = None
            try:
                with patch.object(engine, "voices", return_value=[{"name": "한국어", "culture": "ko-KR"}]), patch.object(engine, "_run", side_effect=lambda p: write_wave(p["path"])), patch("app.services.soundboard_store.SoundboardStore", return_value=store), patch("app.services.soundboard_audio.AudioDriver.validate", side_effect=validate):
                    tool = TTSTool(root, SimpleNamespace(dark_mode=ThemeMode("dark")), engine)
                    tool.pack()
                    deadline = time.monotonic() + 3
                    while tool.busy and time.monotonic() < deadline:
                        root.update()
                        time.sleep(.005)
                    self.assertFalse(tool.busy)
                    tool.text.insert("1.0", "등록 중 종료")
                    tool.generate(True)
                    self.assertTrue(entered.wait(3))
                    tool.destroy()
                    tool.executor.shutdown(wait=True)
                    self.assertFalse(store.items())
                    self.assertFalse(list(store.folder.glob("*.wav")))
                    self.assertFalse(list(store.folder.glob("*.tmp")))
            finally:
                if tool:
                    tool.destroy()
                    tool.executor.shutdown(wait=True)
                root.destroy()
                del tool
                gc.collect()

    def test_one_time_selection_refresh_dispatch_and_direct_registration(self):
        root = tk.Tk()
        engine = FakeEngine()
        tool = TTSTool(root, SimpleNamespace(dark_mode=ThemeMode("dark")), engine)
        tool.pack(fill="both", expand=True)
        def until(predicate):
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                root.update()
                if predicate():
                    return
                time.sleep(.005)
            self.fail("TTS 화면 작업 시간 초과")
        try:
            until(lambda: not tool.busy and not tool.discovering)
            tool.text.insert("1.0", "한글 첫 줄\n두 번째 줄")
            tool.generate(play_once=True)
            self.assertIn("장치", tool.status.get())
            self.assertFalse(engine.calls)
            tool.output_device.current(0)
            tool.refresh_devices()
            until(lambda: not tool.discovering)
            self.assertEqual(tool.output_device.current(), 0)
            tool.rate.set(2)
            tool.volume.set(30)
            robot = builtin_presets()[3]["settings"]
            tool.fx.load(robot)
            with patch("app.tools.file_tts.filedialog.asksaveasfilename", side_effect=AssertionError("일회용 출력에 저장 창이 열림")):
                tool.generate(play_once=True)
                until(lambda: not tool.busy)
            self.assertEqual(engine.calls[-1], ("played", ("한글 첫 줄\n두 번째 줄", self.devices[0], "한국어", 2, 30, robot)))
            self.assertIn("폐기 완료", tool.status.get())
            tool.generate(True)
            until(lambda: not tool.busy)
            self.assertEqual(engine.calls[-1][0], "added")
            self.assertEqual(engine.calls[-1][1][1], "한글 첫 줄")
            self.assertEqual(engine.calls[-1][1][-1], robot)
            self.devices = [{"id": "other", "name": "동일 이름", "channels": 2}]
            tool.refresh_devices()
            until(lambda: not tool.discovering)
            self.assertEqual(tool.output_device.current(), -1)
            self.assertIn("다시 선택", tool.status.get())
        finally:
            tool.destroy()
            tool.executor.shutdown(wait=True)
            root.destroy()
            del tool
            gc.collect()

    def test_registration_three_themes_save_and_destroy(self):
        registry = ToolRegistry()
        register(registry)
        self.assertEqual(registry.tools_for("파일")[0].id, "files.tts")
        root = tk.Tk()
        try:
            for theme in ("dark", "light", "green"):
                engine = FakeEngine()
                tool = TTSTool(root, SimpleNamespace(dark_mode=ThemeMode(theme)), engine)
                tool.pack(fill="both", expand=True)
                def pump():
                    until = time.monotonic() + .15
                    while time.monotonic() < until:
                        root.update()
                        time.sleep(.005)
                pump()
                self.assertEqual(tool.voice.current(), 1)
                self.assertFalse(tool.fx.snapshot()["enabled"])
                tool.generate()
                self.assertIn("입력", tool.status.get())
                tool.text.insert("1.0", "안녕하세요.")
                with patch("app.tools.file_tts.filedialog.asksaveasfilename", return_value=""):
                    tool.generate()
                self.assertFalse(engine.calls)
                with patch("app.tools.file_tts.filedialog.asksaveasfilename", return_value="한글.wav"):
                    tool.generate()
                pump()
                self.assertEqual(engine.calls[0], ("안녕하세요.", "한글.wav", "한국어", 0, 100, default_settings()))
                self.assertIn("저장 완료", tool.status.get())
                timer = tool.timer
                tool.destroy()
                tool.executor.shutdown(wait=True)
                self.assertTrue(engine.closed)
                self.assertNotIn(timer, root.tk.call("after", "info"))
                del tool
                gc.collect()
        finally:
            root.destroy()
