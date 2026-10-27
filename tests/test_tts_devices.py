"""RUN_TTS_DEVICES=1일 때만 실제 음성 엔진·케이블 출력을 검사한다."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app.services.soundboard_audio import AudioDriver
from app.services.soundboard_store import SoundboardStore
from app.services.tts import WindowsTTS


@unittest.skipUnless(os.environ.get("RUN_TTS_DEVICES") == "1", "실제 케이블 출력은 명시적으로 실행")
class RealTTSTests(unittest.TestCase):
    def test_real_korean_cable_output_cleanup_and_registration(self):
        import soundfile as sf
        engine = WindowsTTS()
        voices = engine.voices()
        voice = next((v["name"] for v in voices if v["culture"].startswith("ko")), None)
        self.assertIsNotNone(voice, "한국어 SAPI 음성이 필요합니다.")
        output = next((d for d in AudioDriver().devices() if "CABLE Input" in d["name"]), None)
        self.assertIsNotNone(output, "VB-Audio CABLE Input 장치가 필요합니다.")
        temporary_paths = []
        generate = engine.generate
        def capture(*args):
            result = generate(*args)
            temporary_paths.append(Path(result))
            data, rate = sf.read(result)
            self.assertGreater(rate, 0)
            self.assertGreater(abs(data).max(), 0, "실제 음성 신호가 없습니다.")
            return result
        with patch.object(engine, "generate", side_effect=capture):
            self.assertEqual(engine.play_once("일회용 음성 출력 테스트입니다.", output, voice, volume=20), output["name"])
        self.assertTrue(temporary_paths)
        for path in temporary_paths:
            self.assertFalse(path.exists())
            self.assertFalse(path.parent.exists())
        with tempfile.TemporaryDirectory() as directory:
            store = SoundboardStore(directory)
            with patch("app.services.soundboard_store.SoundboardStore", return_value=store):
                engine.add_to_soundboard("사운드보드 등록 테스트입니다.", "실제 한국어 음성", voice, volume=20)
            item = store.items()[0]
            self.assertEqual(item["title"], "실제 한국어 음성")
            AudioDriver().validate(store.resolve(item["path"]))
        engine.close()
