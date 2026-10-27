import gc
from pathlib import Path
import tempfile
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import wave

from app.palette import ThemeMode
from app.services.tts import WindowsTTS
from app.tools.file_tts import TTSTool, register
from app.tool_registry import ToolRegistry


def write_wave(path):
    with wave.open(str(path), "wb") as sound:
        sound.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        sound.writeframes(b"\0\0" * 100)


class TTSTests(unittest.TestCase):
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


class TTSUITests(unittest.TestCase):
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
                tool.generate()
                self.assertIn("입력", tool.status.get())
                tool.text.insert("1.0", "안녕하세요.")
                with patch("app.tools.file_tts.filedialog.asksaveasfilename", return_value=""):
                    tool.generate()
                self.assertFalse(engine.calls)
                with patch("app.tools.file_tts.filedialog.asksaveasfilename", return_value="한글.wav"):
                    tool.generate()
                pump()
                self.assertEqual(engine.calls[0], ("안녕하세요.", "한글.wav", "한국어", 0, 100))
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
