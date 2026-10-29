import gc
from pathlib import Path
import tempfile
import threading
import time
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from app.palette import ThemeMode, palette
from app.services.soundboard_audio import AudioDriver
from app.services.soundboard_store import SoundboardStore
from app.services.tts import WindowsTTS
from app.services.voice_fx import FXRenderer, builtin_presets, configured, default_settings
from app.services.voice_fx_soundboard import copy_with_fx
from app.services.voice_fx_store import PresetStore
from app.tools.file_tts import TTSTool
from app.tools.voice_fx_editor import VoiceFXEditor


def write_audio(path):
    t = np.arange(22050) / 22050
    sf.write(path, .2 * np.sin(2 * np.pi * 440 * t), 22050)


def pump(root, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(.005)
    raise AssertionError("화면 작업 제한 시간 초과")


class FXIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for module in ("app.services.voice_fx", "app.services.voice_fx_store", "app.services.voice_fx_log"):
            patcher = patch(module + ".data_directory", return_value=self.root)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_tts_source_reused_remix_and_invalidated_by_synthesis_settings(self):
        engine = WindowsTTS()
        output = self.root / "out.wav"
        with patch.object(engine, "_run", side_effect=lambda p: write_audio(p["path"])) as synth:
            engine.generate("원본", output, effect=default_settings())
            original = engine._source_file.read_bytes()
            engine.generate("원본", output, effect=configured(pitch={"semitones": 3}))
            engine.render_cached(configured(robot={}))
            engine.generate("원본", output, effect=configured(robot={}))
            self.assertEqual(synth.call_count, 1)
            self.assertEqual(engine._source_file.read_bytes(), original)
            engine.generate("원본", output, volume=30, effect=configured(robot={}))
            self.assertEqual(synth.call_count, 2)
            engine.generate("다른 텍스트", output, volume=30, effect=default_settings())
            self.assertEqual(synth.call_count, 3)
        folder = engine._source_file.parent
        engine.close()
        self.assertFalse(folder.exists())

    def test_preview_original_modified_reuses_source_and_cleans_playback(self):
        engine = WindowsTTS()
        played = []
        def capture(path, *args):
            played.append((Path(path), sf.read(path)[0]))
        with patch.object(engine, "_run", side_effect=lambda p: write_audio(p["path"])) as synth, patch.object(AudioDriver, "play", side_effect=capture):
            for settings in (default_settings(), configured(robot={})):
                engine.play_once("비교", {"id": "speaker", "name": "출력"}, effect=settings, preview_seconds=12)
            self.assertEqual(synth.call_count, 1)
        self.assertFalse(np.allclose(played[0][1], played[1][1]))
        self.assertTrue(all(not path.exists() for path, _ in played))
        self.assertIsNotNone(engine._source_file)
        engine.close()

    def test_source_generation_cancel_cleanup_and_retry(self):
        engine = WindowsTTS()
        def cancelled(p):
            write_audio(p["path"])
            engine.cancel.set()
        target = self.root / "voice.wav"
        target.write_bytes(b"unchanged")
        with patch.object(engine, "_run", side_effect=cancelled):
            with self.assertRaises(RuntimeError):
                engine.generate("중단", target, effect=configured(robot={}))
        self.assertEqual(target.read_bytes(), b"unchanged")
        self.assertIsNone(engine._session)
        engine.reset_cancel()
        with patch.object(engine, "_run", side_effect=lambda p: write_audio(p["path"])):
            engine.generate("재시도", target, effect=configured(robot={}))
        self.assertEqual(sf.info(target).frames, 22050)
        engine.close()

    def test_batch_copies_preserve_originals_and_failure_rolls_back_batch(self):
        store = SoundboardStore(self.root)
        source = self.root / "source.wav"
        write_audio(source)
        ids = [store.add(), store.add()]
        for identity in ids:
            store.register_file(identity, source, AudioDriver().validate)
        originals = store.items()
        contents = [store.resolve(i["path"]).read_bytes() for i in originals]
        renderer = FXRenderer(self.root / "cache")
        cancel = threading.Event()
        created = copy_with_fx(store, ids, configured(reverse={}), cancel, renderer=renderer)
        self.assertEqual(len(created), 2)
        self.assertEqual(store.items()[:2], originals)
        for identity in created:
            store.delete(identity)
        register = store.register_file
        calls = []
        def fail_second(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 2:
                raise OSError("등록 실패")
            return register(*args, **kwargs)
        with patch.object(store, "register_file", side_effect=fail_second):
            with self.assertRaises(OSError):
                copy_with_fx(store, ids, configured(robot={}), cancel, renderer=renderer)
        self.assertEqual(store.items(), originals)
        self.assertEqual([store.resolve(i["path"]).read_bytes() for i in originals], contents)
        self.assertEqual(len(list(store.folder.glob("*.wav"))), 2)

    def test_editor_three_themes_order_state_presets_and_restart(self):
        root = tk.Tk()
        root.geometry("520x650")
        try:
            for theme in ("dark", "light", "green"):
                status = tk.StringVar()
                editor = VoiceFXEditor(root, palette(ThemeMode(theme)), status, PresetStore(self.root / theme))
                editor.pack(fill="both", expand=True)
                root.update()
                editor.preset.current(3)
                editor.select_preset()
                self.assertTrue(editor.snapshot()["enabled"])
                before = editor.snapshot()["chain"][0]["id"]
                editor.move(0, 1)
                self.assertEqual(editor.snapshot()["chain"][1]["id"], before)
                self.assertIn("수정됨", editor.preset.get())
                editor.expand("echo")
                editor.manage_open.set(True)
                editor.toggle_manager()
                root.update()
                self.assertTrue(editor.manager.winfo_ismapped())
                self.assertGreater(editor.canvas.bbox("all")[3], editor.canvas.winfo_height())
                settings = editor.snapshot()
                editor.persist()
                editor.destroy()
                self.assertEqual(PresetStore(self.root / theme).current(), settings)
                del editor
                gc.collect()
        finally:
            root.destroy()

    def test_tts_ui_remains_responsive_cancel_duplicate_and_text_preserved(self):
        root = tk.Tk()
        engine = WindowsTTS()
        entered = threading.Event()
        def synth(payload):
            entered.set()
            if not engine.cancel.wait(5):
                raise AssertionError("취소 전달 실패")
            raise RuntimeError("생성 취소")
        tool = None
        try:
            with patch.object(engine, "voices", return_value=[{"name": "한국어", "culture": "ko-KR"}]), patch.object(AudioDriver, "devices", return_value=[]), patch.object(engine, "_run", side_effect=synth) as run:
                tool = TTSTool(root, SimpleNamespace(dark_mode=ThemeMode("dark")), engine)
                tool.pack(fill="both", expand=True)
                pump(root, lambda: not tool.busy and not tool.discovering)
                tool.text.insert("1.0", "유지할 텍스트")
                tool.fx.load(builtin_presets()[3]["settings"])
                self.assertEqual(tool.text.get("1.0", "end-1c"), "유지할 텍스트")
                with patch("app.tools.file_tts.filedialog.asksaveasfilename", return_value=str(self.root / "out.wav")):
                    tool.generate()
                    self.assertTrue(entered.wait(3))
                    tool.generate()
                updated = []
                root.after(10, lambda: updated.append(True))
                pump(root, lambda: bool(updated))
                self.assertEqual(run.call_count, 1)
                tool.cancel_work()
                pump(root, lambda: not tool.busy)
                self.assertIn("취소", tool.status.get())
                self.assertFalse((self.root / "out.wav").exists())
                self.assertIn("10,000", tool.count.get())
        finally:
            if tool:
                tool.destroy()
                tool.executor.shutdown(wait=True)
            root.destroy()
            del tool
            gc.collect()


if __name__ == "__main__":
    unittest.main()
