from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import os
import sys
import time
import unittest
from unittest.mock import patch

import numpy as np
import soundfile as sf

from app.services.voice_fx import (EFFECTS, FXRenderer, builtin_presets, configured,
                                   default_settings, process, validate_settings)
from app.services.voice_fx_store import PresetStore


def tone(rate=22050, seconds=.5, channels=1):
    t = np.arange(int(rate * seconds)) / rate
    data = .2 * np.sin(2 * np.pi * 440 * t)
    data *= np.minimum(1, t * 50) * np.minimum(1, (seconds - t) * 50)
    return np.repeat(data[:, None], channels, axis=1).astype(np.float32)


def dominant(samples, rate):
    mono = samples[:, 0]
    return np.argmax(np.abs(np.fft.rfft(mono * np.hanning(len(mono))))) * rate / len(mono)


class VoiceFXTests(unittest.TestCase):
    def test_every_effect_and_builtin_produces_finite_bounded_audio(self):
        for rate, channels in ((8000, 1), (22050, 2), (48000, 1)):
            samples = tone(rate, .15, channels)
            for key in EFFECTS:
                with self.subTest(rate=rate, channels=channels, effect=key):
                    result = process(samples, rate, configured(**{key: {}}))
                    self.assertEqual(result.shape[1], channels)
                    self.assertTrue(np.isfinite(result).all())
                    self.assertLessEqual(np.max(np.abs(result)), .201)
                    self.assertTrue(len(result))
        for preset in builtin_presets():
            with self.subTest(preset=preset["name"]):
                result = process(tone(), 22050, preset["settings"])
                self.assertGreater(np.max(np.abs(result)), .0001)

    def test_pitch_speed_are_independent(self):
        source = tone(seconds=1)
        pitched = process(source, 22050, configured(pitch={"semitones": 12}))
        fast = process(source, 22050, configured(speed={"factor": 2}))
        self.assertLess(abs(len(pitched) - len(source)), 100)
        self.assertLess(abs(len(fast) - len(source) / 2), 100)
        self.assertAlmostEqual(dominant(pitched, 22050), 880, delta=8)
        self.assertAlmostEqual(dominant(fast, 22050), 440, delta=8)

    def test_formant_moves_envelope_without_shifting_harmonics(self):
        rate = 22050
        t = np.arange(rate) / rate
        samples = np.zeros(rate)
        for frequency in range(100, 4001, 100):
            gain = np.exp(-.5 * ((frequency - 800) / 170) ** 2)
            samples += gain * np.sin(2 * np.pi * frequency * t)
        samples = (.1 * samples / np.max(np.abs(samples)))[:, None].astype(np.float32)
        result = process(samples, rate, configured(formant={"semitones": 5}))
        self.assertEqual(result.shape, samples.shape)
        before, after = dominant(samples, rate), dominant(result, rate)
        self.assertGreater(after, before + 100)
        spectrum = np.abs(np.fft.rfft(result[:, 0]))
        # Harmonic spacing remains 100Hz, rather than the 133Hz of a pitch shift.
        peaks = np.argsort(spectrum)[-8:]
        self.assertTrue(all(min(p % 100, 100 - p % 100) < 3 for p in peaks))

    def test_chain_order_reverse_tails_silence_and_cancel(self):
        source = tone()
        one = configured(reverse={}, echo={"delay": .1})
        two = deepcopy(one)
        two["chain"] = list(reversed(two["chain"]))
        a, b = process(source, 22050, one), process(source, 22050, two)
        self.assertGreater(len(a), len(source))
        self.assertFalse(np.allclose(a, b))
        self.assertGreater(np.max(np.abs(a[len(source):])), .001)
        silence = process(np.zeros_like(source), 22050, builtin_presets()[5]["settings"])
        np.testing.assert_array_equal(silence, 0)
        event = threading.Event()
        event.set()
        with self.assertRaisesRegex(RuntimeError, "취소"):
            process(source, 22050, one, event)
        np.testing.assert_array_equal(source, tone())

    def test_strict_settings_and_disabled_bypass(self):
        source = tone()
        np.testing.assert_array_equal(process(source, 22050, default_settings()), source)
        invalid = [None, {}, {"version": 9, "enabled": True, "chain": []}]
        for value in (float("nan"), float("inf"), 13, True, "2"):
            settings = configured(pitch={})
            settings["chain"][0]["params"]["semitones"] = value
            invalid.append(settings)
        bad = configured()
        bad["chain"][0]["id"] = "missing"
        invalid.append(bad)
        for value in invalid:
            with self.assertRaises(ValueError):
                validate_settings(value)

    def test_cache_reuse_hash_invalidation_corruption_preview_and_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.wav"
            sf.write(source, tone(seconds=2), 22050)
            renderer = FXRenderer(root / "cache", max_bytes=300_000)
            settings = configured(robot={})
            first = renderer.render(source, settings)
            with patch("app.services.voice_fx.process", side_effect=AssertionError("캐시 미사용")):
                self.assertEqual(renderer.render(source, settings), first)
            first.write_bytes(b"corrupted")
            self.assertEqual(renderer.render(source, settings), first)
            self.assertEqual(sf.info(first).frames, 44100)
            short = renderer.render(source, settings, preview_seconds=1)
            self.assertEqual(sf.info(short).frames, 22050)
            sf.write(source, tone(seconds=1), 22050)
            changed = renderer.render(source, settings)
            self.assertNotEqual(changed, first)
            settings["chain"].reverse()
            self.assertNotEqual(renderer.render(source, settings), changed)
            self.assertLessEqual(sum(p.stat().st_size for p in renderer.folder.glob("*.wav")), renderer.max_bytes)
            event = threading.Event()
            event.set()
            with self.assertRaises(RuntimeError):
                renderer.render(source, settings, event)
            self.assertFalse(list(renderer.folder.glob(".render-*")))

    def test_short_audio_stereo_and_varied_rates(self):
        for rate in (8000, 16000, 44100, 96000):
            source = tone(rate, .02, 2)
            for fx in (configured(formant={"semitones": -3}), configured(pitch={"semitones": -3}), configured(speed={"factor": .5})):
                result = process(source, rate, fx)
                self.assertEqual(result.shape[1], 2)
                self.assertTrue(np.isfinite(result).all())

    def test_long_audio_limits_missing_dependency_and_mid_effect_cancel(self):
        samples = tone(22050, 20, 2)
        result = process(samples, 22050, configured(robot={}, compressor={}, eq={"mid": -3}))
        self.assertEqual(result.shape, samples.shape)
        with patch("app.services.voice_fx.MAX_SAMPLES", 1000):
            with self.assertRaises(ValueError):
                process(tone(8000, .05), 8000, configured(echo={}))
            with self.assertRaises(ValueError):
                process(tone(8000, .1), 8000, configured(speed={"factor": .5}))
        with patch.dict(sys.modules, {"pedalboard": None}):
            with self.assertRaisesRegex(RuntimeError, "라이브러리"):
                process(tone(), 22050, configured(robot={}))
        event = threading.Event()
        with self.assertRaisesRegex(RuntimeError, "취소"):
            process(tone(), 22050, configured(robot={}), event, lambda _: event.set())

    def test_invalid_audio_cache_metadata_and_old_cache_cleanup(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "voice.wav"
            source.write_bytes(b"not audio")
            renderer = FXRenderer(root / "cache")
            with self.assertRaises((ValueError, sf.LibsndfileError)):
                renderer.render(source, configured(robot={}))
            sf.write(source, tone(), 22050)
            cached = renderer.render(source, configured(robot={}))
            cached.with_suffix(".json").write_text("[]", encoding="utf-8")
            self.assertEqual(renderer.render(source, configured(robot={})), cached)
            old = time.time() - 31 * 86400
            os.utime(cached, (old, old))
            unrelated = renderer.folder / "user.wav"
            unrelated.write_bytes(b"keep")
            renderer.prune()
            self.assertFalse(cached.exists())
            self.assertEqual(unrelated.read_bytes(), b"keep")
            sf.write(source, np.array([[float("nan")]], dtype=np.float32), 22050, subtype="FLOAT")
            with self.assertRaises(ValueError):
                renderer.render(source, configured(robot={}))


class PresetTests(unittest.TestCase):
    def test_crud_duplicate_export_import_and_restart_order(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PresetStore(Path(folder) / "user")
            settings = configured(robot={}, echo={})
            settings["chain"].reverse()
            first = store.save("나만의 로봇", settings)
            changed = store.save("변경 이름", settings, first["id"])
            clone = store.save("복제", changed["settings"])
            self.assertNotEqual(first["id"], clone["id"])
            store.save_current(settings)
            restarted = PresetStore(store.folder)
            self.assertEqual(restarted.current(), settings)
            self.assertEqual(restarted.users()[0], changed)
            exported = Path(folder) / "export.json"
            store.export(exported, changed)
            imported = store.import_file(exported)[0]
            self.assertNotEqual(imported["id"], changed["id"])
            self.assertEqual(imported["settings"], settings)
            store.delete(first["id"])
            self.assertEqual(len(store.users()), 2)

    def test_builtins_protected_corruption_and_invalid_import_are_atomic(self):
        with tempfile.TemporaryDirectory() as folder:
            store = PresetStore(folder)
            first = store.save("정상", configured())
            before = store.path.read_bytes()
            for action in (lambda: store.delete("builtin-robot"), lambda: store.save("변경", configured(), "builtin-robot")):
                with self.assertRaises(ValueError):
                    action()
            imported = Path(folder) / "import.json"
            imported.write_text(json.dumps({"version": 1, "presets": [first, {}]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                store.import_file(imported)
            self.assertEqual(store.path.read_bytes(), before)
            store.path.write_bytes(b"broken")
            with self.assertRaises(ValueError):
                store.save("추가", configured())
            self.assertEqual(store.path.read_bytes(), b"broken")


if __name__ == "__main__":
    unittest.main()
