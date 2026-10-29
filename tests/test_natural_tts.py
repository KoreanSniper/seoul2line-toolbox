import gc
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import urllib.error

import numpy as np
import soundfile as sf

from app.palette import ThemeMode
from app.services.natural_tts import NeuralModel, NaturalTTS, PREFIX, split_text, voice_records
from app.services.tts import WindowsTTS
from app.services.voice_fx import configured, default_settings
from app.tools.file_tts import TTSTool


def wave_file(path):
    t = np.arange(2205) / 22050
    sf.write(path, .2 * np.sin(2 * np.pi * 440 * t), 22050)


class NaturalTTSTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module in ("app.services.natural_tts", "app.services.voice_fx", "app.services.voice_fx_store", "app.services.voice_fx_log"):
            patcher = patch(module + ".data_directory", return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    def model(self, content=b"valid model"):
        model = NeuralModel(self.root / "models")
        model.manifest = {"repository": "Supertone/supertonic-3", "revision": "pinned", "files": [
            {"path": "onnx/model.onnx", "size": len(content), "sha256": hashlib.sha256(content).hexdigest()}]}
        return model

    def test_ten_voices_and_bounded_chunks_preserve_text(self):
        records = voice_records()
        self.assertEqual(len({v["name"] for v in records}), 10)
        self.assertEqual(sum("여성" in v["label"] for v in records), 5)
        text = "첫 번째 문장입니다.\n" + "긴문장" * 300 + " 끝!\n\n마지막 문장입니다."
        chunks = split_text(text)
        self.assertTrue(all(0 < len(c) <= 120 for c in chunks))
        self.assertEqual("".join("".join(chunks).split()), "".join(text.split()))

    def test_install_integrity_reuse_and_corrupt_marker(self):
        model = self.model()
        content = b"valid model"
        with patch("urllib.request.urlopen", return_value=io.BytesIO(content)) as fetch:
            model.install()
            fetch.assert_called_once()
        self.assertTrue(model.installed())
        model.verify()
        with patch("urllib.request.urlopen", side_effect=AssertionError("완료 파일 재다운로드")):
            model.install()
        path = model.folder / "onnx/model.onnx"
        path.write_bytes(b"bad")
        self.assertFalse(model.installed())
        with self.assertRaises(ValueError):
            model.verify()
        with patch("urllib.request.urlopen", return_value=io.BytesIO(content)):
            model.install()
        self.assertTrue(model.installed())
        model.marker.write_text("[]", encoding="utf-8")
        self.assertFalse(model.installed())

    def test_download_cancel_hash_failure_and_network_error_cleanup(self):
        model = self.model()
        cancel = threading.Event()
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"valid model")):
            with self.assertRaisesRegex(RuntimeError, "취소"):
                model.install(cancel, lambda _: cancel.set())
        self.assertFalse(model.installed())
        self.assertFalse(list(model.folder.rglob("*.part")))
        cancel.clear()
        path = model.folder / "onnx/model.onnx"
        path.write_bytes(b"old file")
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"wrong model")):
            with self.assertRaises(ValueError):
                model.install(cancel)
        self.assertEqual(path.read_bytes(), b"old file")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("offline")) as fetch:
            with self.assertRaisesRegex(RuntimeError, "인터넷"):
                model.install(cancel)
            self.assertEqual(fetch.call_count, 3)
        self.assertFalse(list(model.folder.rglob("*.part")))

    def test_neural_synthesis_korean_speed_volume_chunks_and_cancel(self):
        model = Mock()
        model.installed.return_value = True
        model.sample_rate = 44100
        engine = NaturalTTS(model)
        fake = Mock(sample_rate=44100)
        fake.synthesize.return_value = (np.ones((1, 4410), dtype=np.float32) * .4, np.array([.1]))
        engine.model = fake
        target = self.root / "out.wav"
        cancel = threading.Event()
        engine.synthesize("문장" * 100, target, PREFIX + "F1", 10, 25, cancel)
        actual, rate = sf.read(target)
        self.assertEqual(rate, 44100)
        self.assertAlmostEqual(np.max(actual), .1, delta=.001)
        self.assertEqual(fake.synthesize.call_count, 2)
        for call in fake.synthesize.call_args_list:
            self.assertEqual(call.kwargs["lang"], "ko")
            self.assertEqual(call.kwargs["total_steps"], 10)
            self.assertAlmostEqual(call.kwargs["speed"], 2 ** .5)
            self.assertLessEqual(len(call.args[0]), 120)
        fake.synthesize.side_effect = lambda *a, **kw: (cancel.set() or np.ones((1, 100)), np.array([.1]))
        with self.assertRaisesRegex(RuntimeError, "취소"):
            engine.synthesize("취소", target, PREFIX + "M2", 0, 100, cancel)
        self.assertIsNone(engine.model)

    def test_load_is_offline_and_bounded_cpu_threads(self):
        assets = Mock(folder=self.root, size_mb=383)
        assets.installed.return_value = True
        fake = Mock(sample_rate=44100)
        fake.synthesize.return_value = (np.ones((1, 100), dtype=np.float32) * .1, np.array([.01]))
        engine = NaturalTTS(assets)
        with patch("supertonic.TTS", return_value=fake) as load, patch("urllib.request.urlopen", side_effect=AssertionError("합성 중 네트워크 요청")):
            for _ in range(2):
                engine.synthesize("안녕", self.root / "out.wav", PREFIX + "F2", 0, 100, threading.Event())
        load.assert_called_once()
        self.assertFalse(load.call_args.kwargs["auto_download"])
        self.assertLessEqual(load.call_args.kwargs["intra_op_num_threads"], 4)
        assets.verify.assert_called_once()
        engine.close()
        self.assertIsNone(engine.model)

    def test_windows_and_neural_voice_lists_priority_and_windows_failure(self):
        engine = WindowsTTS()
        sapi = [{"name": "한국어", "culture": "ko-KR"}]
        with patch.object(engine, "_run", return_value=json.dumps(sapi)), patch.object(NeuralModel, "installed", return_value=False):
            self.assertEqual(engine.voices()[0]["name"], "한국어")
        with patch.object(engine, "_run", return_value=json.dumps(sapi)), patch.object(NeuralModel, "installed", return_value=True):
            self.assertEqual(engine.voices()[0]["name"], PREFIX + "F1")
        with patch.object(engine, "_run", side_effect=OSError("SAPI failure")):
            self.assertEqual(len(engine.voices()), 10)

    def test_public_generation_fx_cache_and_failure_preserve_existing(self):
        engine = WindowsTTS()
        neural = Mock()
        neural.synthesize.side_effect = lambda text, target, *args: wave_file(target)
        engine._natural = neural
        target = self.root / "voice.wav"
        with patch.object(engine, "_run", side_effect=AssertionError("자연음성에 Windows 합성 호출")):
            engine.generate("새 목소리", target, PREFIX + "M1", effect=configured(robot={}))
            engine.generate("새 목소리", target, PREFIX + "M1", effect=configured(reverse={}))
        self.assertEqual(neural.synthesize.call_count, 1)
        self.assertEqual(sf.info(target).samplerate, 22050)
        before = target.read_bytes()
        neural.synthesize.side_effect = RuntimeError("모델 오류")
        with self.assertRaises(RuntimeError):
            engine.generate("다른 문장", target, PREFIX + "M1")
        self.assertEqual(target.read_bytes(), before)
        self.assertFalse(list(self.root.glob(".tts-*")))
        engine.close()

    def test_missing_model_does_not_download_or_change_target(self):
        engine = WindowsTTS()
        target = self.root / "existing.wav"
        target.write_bytes(b"preserved")
        with patch("urllib.request.urlopen", side_effect=AssertionError("명시 설치 없이 네트워크 요청")):
            with self.assertRaisesRegex(ValueError, "설치"):
                engine.generate("안녕하세요", target, PREFIX + "F3")
        self.assertEqual(target.read_bytes(), b"preserved")
        self.assertFalse(list(self.root.glob(".tts-*")))
        engine.close()

    def test_ui_model_setup_refresh_and_text_survive_three_themes(self):
        root = tk.Tk()
        try:
            for theme in ("dark", "light", "green"):
                engine = Mock()
                engine.cancel = threading.Event()
                engine.natural_model_status.return_value = "자연음성 설치 필요"
                engine.voices.return_value = voice_records()
                engine.install_natural.return_value = "자연음성 10종 설치 완료"
                tool = TTSTool(root, SimpleNamespace(dark_mode=ThemeMode(theme)), engine)
                tool.pack(fill="both", expand=True)
                def until(predicate):
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        root.update()
                        if predicate():
                            return
                        time.sleep(.005)
                    self.fail("화면 작업 시간 초과")
                with patch("app.tools.file_tts.AudioDriver.devices", return_value=[]):
                    until(lambda: not tool.busy)
                    tool.text.insert("1.0", "입력 유지")
                    tool.install_natural()
                    until(lambda: not tool.busy)
                    engine.install_natural.assert_called_once()
                    self.assertEqual(len(tool.voices), 10)
                    self.assertIn("자연음성", tool.voice.get())
                    self.assertEqual(tool.text.get("1.0", "end-1c"), "입력 유지")
                tool.destroy()
                tool.executor.shutdown(wait=True)
                del tool
                gc.collect()
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
