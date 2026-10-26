"""Opt-in Windows endpoint check: RUN_SOUNDBOARD_DEVICES=1.

Uses a quiet generated tone, never microphone input. Tests open independent
physical/virtual streams and report API success; listening remains manual.
"""
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest

from app.services.soundboard_audio import AudioDriver, SoundboardAudio


@unittest.skipUnless(os.environ.get("RUN_SOUNDBOARD_DEVICES") == "1", "실제 출력 장치 검사는 명시적으로 실행합니다.")
class WindowsDeviceTests(unittest.TestCase):
    def test_real_physical_virtual_streams_formats_and_rates(self):
        import numpy as np
        import soundfile as sf

        class ObservedDriver(AudioDriver):
            def __init__(self):
                self.started = []
                self.finished = []

            def play(self, path, output, ready, start, cancel, gain):
                self.started.append(output["id"])
                super().play(path, output, ready, start, cancel, gain)
                self.finished.append(output["id"])

        driver = ObservedDriver()
        devices = driver.devices()
        virtual = next((d for d in devices if "CABLE" in d["name"].upper()), None)
        physical = next((d for d in devices if "CABLE" not in d["name"].upper()), None)
        if not physical or not virtual:
            self.skipTest("물리 출력과 VB-Audio 출력의 조합이 필요합니다.")
        outputs = [dict(d, volume=25) for d in (physical, virtual)]
        audio = SoundboardAudio(driver)
        audio.volumes(40, outputs)
        try:
            with tempfile.TemporaryDirectory() as folder:
                for extension, rate, channels in (("wav", 22050, 1), ("ogg", 44100, 2), ("mp3", 48000, 2)):
                    with self.subTest(format=extension, samplerate=rate, channels=channels):
                        path = Path(folder) / ("generated." + extension)
                        t = np.arange(int(rate * .4)) / rate
                        data = (.02 * np.sin(2 * np.pi * 440 * t)).astype("float32")
                        if channels == 2:
                            data = np.column_stack((data, data))
                        sf.write(str(path), data, rate)
                        driver.validate(path)
                        driver.started.clear()
                        driver.finished.clear()
                        audio.toggle(extension, path, outputs)
                        deadline = time.monotonic() + 8
                        while audio.current is not None and time.monotonic() < deadline:
                            time.sleep(.01)
                        self.assertIsNone(audio.current, "출력 스트림 종료 시간 초과")
                        errors = []
                        while not audio.events.empty():
                            event = audio.events.get_nowait()
                            if event[1] == "error":
                                errors.append(event[2])
                        self.assertEqual(errors, [])
                        self.assertCountEqual(driver.started, [o["id"] for o in outputs])
                        self.assertCountEqual(driver.finished, driver.started)
                        print(f"\n실제 출력 성공: {extension.upper()} {rate}Hz {channels}ch / " + " + ".join(o["name"] for o in outputs))
        finally:
            audio.close()
            audio.worker.join(3)
            self.assertFalse(audio.worker.is_alive())


if __name__ == "__main__":
    unittest.main()
