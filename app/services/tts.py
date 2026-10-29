"""Windows의 설치된 SAPI 음성으로 로컬 WAV를 생성한다."""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import wave


VOICE_EFFECTS = {"none": "원본", "robot": "로봇"}


SCRIPT = r"""
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $p = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ($p.action -eq 'voices') {
        $voices = @($s.GetInstalledVoices() | Where-Object Enabled | ForEach-Object {
            @{name=$_.VoiceInfo.Name; culture=$_.VoiceInfo.Culture.Name}
        })
        ConvertTo-Json -InputObject $voices -Compress
    } else {
        if ($p.voice) { $s.SelectVoice($p.voice) }
        $s.Rate = [int]$p.rate
        $s.Volume = [int]$p.volume
        $s.SetOutputToWaveFile($p.path)
        $s.Speak([string]$p.text)
        $s.SetOutputToNull()
    }
} finally { $s.Dispose() }
"""


class WindowsTTS:
    def __init__(self):
        self.cancel = threading.Event()
        self.progress = None
        self._session = None
        self._source_key = None
        self._source_file = None
        self._session_lock = threading.Lock()
        self._renderer = None

    def close(self):
        self.cancel.set()
        self.cleanup()

    def cleanup(self):
        # The active worker owns its temporary source until it observes cancellation.
        if self._session_lock.acquire(blocking=False):
            try:
                if self._session is not None:
                    self._session.cleanup()
                    self._session = None
                self._source_key = self._source_file = None
            finally:
                self._session_lock.release()

    def reset_cancel(self):
        self.cancel.clear()

    def _cached_generate(self, text, target, voice, rate, volume, settings, preview_seconds):
        from app.services.voice_fx import FXRenderer, atomic_copy, check_cancel, validate_settings
        settings = validate_settings(settings)
        try:
            with self._session_lock:
                check_cancel(self.cancel)
                key = (text, voice, rate, volume)
                if self._session is None:
                    self._session = tempfile.TemporaryDirectory(prefix="toolbox-tts-source-")
                source = Path(self._session.name) / "original.wav"
                if self._source_key != key or not source.exists():
                    if self.progress:
                        self.progress("원본 TTS 생성 중…")
                    # Use the established atomic Windows synthesis path.
                    self.generate(text, source, voice, rate, volume, "none")
                    self._source_key, self._source_file = key, source
                elif self.progress:
                    self.progress("보존한 원본 TTS 재사용")
                self._renderer = self._renderer or FXRenderer()
                rendered = self._renderer.render(source, settings, self.cancel, self.progress, preview_seconds)
                atomic_copy(rendered, target, self.cancel)
                return str(target)
        finally:
            if self.cancel.is_set():
                self.cleanup()

    def render_cached(self, settings):
        from app.services.voice_fx import check_cancel
        try:
            with self._session_lock:
                check_cancel(self.cancel)
                if not self._source_file or not self._source_file.exists() or self._renderer is None:
                    raise ValueError("먼저 원본 미리듣기·저장·출력으로 TTS 음성을 생성하세요.")
                return str(self._renderer.render(self._source_file, settings, self.cancel, self.progress))
        finally:
            if self.cancel.is_set():
                self.cleanup()

    def _run(self, payload):
        if sys.platform != "win32":
            raise RuntimeError("이 도구는 Windows의 설치된 음성을 사용합니다.")
        if self.cancel.is_set():
            raise RuntimeError("음성 생성을 취소했습니다.")
        encoded = base64.b64encode(SCRIPT.encode("utf-16-le")).decode("ascii")
        executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        with subprocess.Popen([str(executable), "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)) as process:
            data = json.dumps(payload, ensure_ascii=True).encode("ascii")
            deadline = time.monotonic() + 180
            try:
                while True:
                    if self.cancel.is_set():
                        raise RuntimeError("음성 생성을 취소했습니다.")
                    if time.monotonic() >= deadline:
                        raise RuntimeError("Windows 음성 엔진의 응답 시간이 초과되었습니다.")
                    try:
                        out, err = process.communicate(input=data, timeout=.1)
                        break
                    except subprocess.TimeoutExpired:
                        data = None
                if process.returncode:
                    raise RuntimeError(err.decode("utf-8", errors="replace").strip() or "Windows 음성 엔진 실행 실패")
                return out.decode("utf-8-sig").strip()
            finally:
                if process.poll() is None:
                    process.kill()
                    process.communicate()

    def voices(self):
        result = json.loads(self._run({"action": "voices"}) or "[]")
        return result if isinstance(result, list) else [result]

    def play_once(self, text, output, voice="", rate=0, volume=100, effect="none", preview_seconds=None):
        from app.services.soundboard_audio import AudioDriver

        if not output.get("id"):
            raise ValueError("일회용 음성을 출력할 장치를 선택하세요.")
        # 재생 스트림이 닫힌 뒤 정상 종료·오류·화면 종료 모두 임시 WAV를 제거한다.
        with tempfile.TemporaryDirectory(prefix="toolbox-tts-once-") as directory:
            source = Path(directory) / "voice.wav"
            self.generate(text, source, voice, rate, volume, effect, preview_seconds)
            if self.cancel.is_set():
                raise RuntimeError("일회용 음성 출력을 취소했습니다.")
            ready, start = threading.Event(), threading.Event()
            start.set()
            # 음성 생성 단계에서 볼륨을 적용했으므로 재생 배율은 1이다.
            AudioDriver().play(source, output, ready, start, self.cancel, lambda _identity: 1.0)
        return output["name"]

    def add_to_soundboard(self, text, title, voice="", rate=0, volume=100, effect="none"):
        from app.services.soundboard_audio import AudioDriver
        from app.services.soundboard_store import SoundboardStore

        title = title.strip()
        if not title or len(title) > 100:
            raise ValueError("사운드 제목은 1~100자로 입력하세요.")
        with tempfile.TemporaryDirectory(prefix="toolbox-tts-") as directory:
            source = Path(directory) / "voice.wav"
            self.generate(text, source, voice, rate, volume, effect)
            if self.cancel.is_set():
                raise RuntimeError("음성 생성을 취소했습니다.")
            store = SoundboardStore()
            identity = store.add()
            try:
                store.rename(identity, title)
                driver = AudioDriver()
                store.register_file(identity, source,
                                    lambda path: driver.validate(path, cancel=self.cancel), self.cancel)
                if self.cancel.is_set():
                    raise RuntimeError("음성 생성을 취소했습니다.")
            except BaseException:
                store.delete(identity)
                raise
        return title

    def _robot_effect(self, source, target):
        """90Hz 링 변조로 길이·출력 형식·볼륨 상한을 유지하는 금속성 효과."""
        import numpy as np
        import soundfile as sf

        with sf.SoundFile(source) as original, sf.SoundFile(
                target, mode="w", samplerate=original.samplerate,
                channels=original.channels, subtype="PCM_16", format="WAV") as result:
            offset = 0
            for samples in original.blocks(blocksize=16384, dtype="float32", always_2d=True):
                if self.cancel.is_set():
                    raise RuntimeError("음성 변형을 취소했습니다.")
                # 블록 경계에서도 위상을 이어가며 무음은 그대로 유지한다.
                phase = (np.arange(len(samples)) + offset) * (2 * np.pi * 90 / original.samplerate)
                carrier = .25 + .75 * np.sin(phase)
                result.write(np.clip(samples * carrier[:, None], -1, 1))
                offset += len(samples)

    def generate(self, text, target, voice="", rate=0, volume=100, effect="none", preview_seconds=None):
        if not text.strip() or len(text) > 10000:
            raise ValueError("텍스트를 1~10,000자 입력하세요.")
        if not -10 <= rate <= 10 or not 0 <= volume <= 100:
            raise ValueError("속도는 -10~10, 볼륨은 0~100 범위로 입력하세요.")
        target = Path(target).resolve()
        if target.suffix.lower() != ".wav":
            raise ValueError("저장 파일 확장자는 .wav여야 합니다.")
        if isinstance(effect, dict):
            return self._cached_generate(text, target, voice, rate, volume, effect, preview_seconds)
        if effect not in VOICE_EFFECTS:
            raise ValueError("지원하지 않는 목소리 변형입니다.")
        handle, temporary = tempfile.mkstemp(prefix=".tts-", suffix=".wav", dir=target.parent)
        os.close(handle)
        processed = temporary + ".effect.wav"
        try:
            self._run({"action": "generate", "text": text, "voice": voice,
                       "rate": rate, "volume": volume, "path": temporary})
            if self.cancel.is_set():
                raise RuntimeError("음성 생성을 취소했습니다.")
            with wave.open(temporary, "rb") as sound:
                if sound.getnframes() <= 0:
                    raise ValueError("음성 엔진이 빈 파일을 생성했습니다.")
            if effect == "robot":
                self._robot_effect(temporary, processed)
                os.replace(processed, temporary)
            if self.cancel.is_set():
                raise RuntimeError("음성 생성을 취소했습니다.")
            os.replace(temporary, target)
            return str(target)
        finally:
            Path(temporary).unlink(missing_ok=True)
            Path(processed).unlink(missing_ok=True)
