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

    def close(self):
        self.cancel.set()

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

    def play_once(self, text, output, voice="", rate=0, volume=100):
        from app.services.soundboard_audio import AudioDriver

        if not output.get("id"):
            raise ValueError("일회용 음성을 출력할 장치를 선택하세요.")
        # 재생 스트림이 닫힌 뒤 정상 종료·오류·화면 종료 모두 임시 WAV를 제거한다.
        with tempfile.TemporaryDirectory(prefix="toolbox-tts-once-") as directory:
            source = Path(directory) / "voice.wav"
            self.generate(text, source, voice, rate, volume)
            if self.cancel.is_set():
                raise RuntimeError("일회용 음성 출력을 취소했습니다.")
            ready, start = threading.Event(), threading.Event()
            start.set()
            # 음성 생성 단계에서 볼륨을 적용했으므로 재생 배율은 1이다.
            AudioDriver().play(source, output, ready, start, self.cancel, lambda _identity: 1.0)
        return output["name"]

    def add_to_soundboard(self, text, title, voice="", rate=0, volume=100):
        from app.services.soundboard_audio import AudioDriver
        from app.services.soundboard_store import SoundboardStore

        title = title.strip()
        if not title or len(title) > 100:
            raise ValueError("사운드 제목은 1~100자로 입력하세요.")
        with tempfile.TemporaryDirectory(prefix="toolbox-tts-") as directory:
            source = Path(directory) / "voice.wav"
            self.generate(text, source, voice, rate, volume)
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

    def generate(self, text, target, voice="", rate=0, volume=100):
        if not text.strip() or len(text) > 10000:
            raise ValueError("텍스트를 1~10,000자 입력하세요.")
        if not -10 <= rate <= 10 or not 0 <= volume <= 100:
            raise ValueError("속도는 -10~10, 볼륨은 0~100 범위로 입력하세요.")
        target = Path(target).resolve()
        if target.suffix.lower() != ".wav":
            raise ValueError("저장 파일 확장자는 .wav여야 합니다.")
        handle, temporary = tempfile.mkstemp(prefix=".tts-", suffix=".wav", dir=target.parent)
        os.close(handle)
        try:
            self._run({"action": "generate", "text": text, "voice": voice,
                       "rate": rate, "volume": volume, "path": temporary})
            if self.cancel.is_set():
                raise RuntimeError("음성 생성을 취소했습니다.")
            with wave.open(temporary, "rb") as sound:
                if sound.getnframes() <= 0:
                    raise ValueError("음성 엔진이 빈 파일을 생성했습니다.")
            os.replace(temporary, target)
            return str(target)
        finally:
            Path(temporary).unlink(missing_ok=True)
