"""Local Korean neural voices. Network is used only for explicit model setup."""
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request

from app.paths import data_directory
from app.services.voice_fx import check_cancel
from app.services.voice_fx_store import atomic_json


PREFIX = "supertonic3/"
VOICE_IDS = tuple(f"{gender}{i}" for gender in ("F", "M") for i in range(1, 6))
MANIFEST = Path(__file__).resolve().parents[1] / "assets" / "tts" / "supertonic3-manifest.json"


def voice_records():
    return [{"name": PREFIX + identity, "culture": "ko-KR", "provider": "supertonic3",
             "label": f"자연음성 · {'여성' if identity.startswith('F') else '남성'} {identity}"}
            for identity in VOICE_IDS]


def digest(path, cancel=None):
    result = hashlib.sha256()
    with open(path, "rb") as stream:
        while block := stream.read(1024 * 1024):
            check_cancel(cancel)
            result.update(block)
    return result.hexdigest()


def split_text(text, limit=120):
    """Bound even a single unpunctuated sentence for cancellation and memory."""
    chunks, pending = [], ""
    for sentence in re.split(r"(?<=[.!?。！？])\s+|\n+", text.strip()):
        sentence = sentence.strip()
        if not sentence:
            continue
        if pending and len(pending) + len(sentence) + 1 <= limit:
            pending += " " + sentence
            continue
        if pending:
            chunks.append(pending)
        while len(sentence) > limit:
            space = sentence.rfind(" ", limit // 2, limit + 1)
            end = space if space > 0 else limit
            chunks.append(sentence[:end].strip())
            sentence = sentence[end:].strip()
        pending = sentence
    if pending:
        chunks.append(pending)
    return chunks


class NeuralModel:
    def __init__(self, root=None):
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.folder = Path(root) if root is not None else data_directory() / "tts_models" / ("supertonic3-" + self.manifest["revision"][:8])
        self.marker = self.folder / "ready.json"

    @property
    def size_mb(self):
        return round(sum(f["size"] for f in self.manifest["files"]) / 1024 / 1024)

    def installed(self):
        try:
            marker = json.loads(self.marker.read_text(encoding="utf-8"))
            if marker["revision"] != self.manifest["revision"]:
                return False
            return all(self._stamp(f) == marker["files"][f["path"]] for f in self.manifest["files"])
        except (OSError, ValueError, KeyError, TypeError):
            return False

    def _stamp(self, entry):
        stat = (self.folder / entry["path"]).stat()
        if stat.st_size != entry["size"]:
            raise ValueError("자연음성 모델 파일 크기가 다릅니다.")
        return [stat.st_size, stat.st_mtime_ns]

    def verify(self, cancel=None):
        for entry in self.manifest["files"]:
            check_cancel(cancel)
            path = self.folder / entry["path"]
            if not path.is_file() or path.stat().st_size != entry["size"] or digest(path, cancel) != entry["sha256"]:
                raise ValueError("자연음성 모델이 없거나 손상되었습니다. '자연음성 설치'로 설치·복구하세요.")

    def install(self, cancel=None, progress=None):
        """Pinned public files, no SDK downloader, auth token or user text uploads."""
        self.folder.mkdir(parents=True, exist_ok=True)
        total = sum(f["size"] for f in self.manifest["files"])
        completed = 0
        try:
            for entry in self.manifest["files"]:
                check_cancel(cancel)
                path = self.folder / entry["path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.is_file() and path.stat().st_size == entry["size"] and digest(path, cancel) == entry["sha256"]:
                    completed += entry["size"]
                    continue
                url = f"https://huggingface.co/{self.manifest['repository']}/resolve/{self.manifest['revision']}/{entry['path']}"
                fd, temporary = tempfile.mkstemp(prefix=".download-", suffix=".part", dir=path.parent)
                os.close(fd)
                try:
                    for attempt in range(3):
                        check_cancel(cancel)
                        downloaded, hasher, last_notice = 0, hashlib.sha256(), 0
                        try:
                            with urllib.request.urlopen(url, timeout=30) as response, open(temporary, "wb") as output:
                                while block := response.read(256 * 1024):
                                    check_cancel(cancel)
                                    downloaded += len(block)
                                    if downloaded > entry["size"]:
                                        raise ValueError("자연음성 모델 파일 크기가 예상과 다릅니다.")
                                    hasher.update(block)
                                    output.write(block)
                                    if progress and time.monotonic() - last_notice >= .25:
                                        progress(f"자연음성 모델 설치: {(completed + downloaded) * 100 / total:.1f}% · {self.size_mb}MiB")
                                        last_notice = time.monotonic()
                            if downloaded != entry["size"] or hasher.hexdigest() != entry["sha256"]:
                                raise ValueError("자연음성 모델 파일 검증에 실패했습니다. 다시 설치하세요.")
                            check_cancel(cancel)
                            os.replace(temporary, path)
                            break
                        except (OSError, urllib.error.URLError):
                            if attempt == 2:
                                raise
                    completed += entry["size"]
                finally:
                    Path(temporary).unlink(missing_ok=True)
            check_cancel(cancel)
            atomic_json(self.marker, {"revision": self.manifest["revision"],
                "files": {f["path"]: self._stamp(f) for f in self.manifest["files"]}})
        except (OSError, urllib.error.URLError) as exc:
            raise RuntimeError("자연음성 모델을 내려받지 못했습니다. 인터넷 연결을 확인한 뒤 다시 설치하세요. 완료된 파일은 재사용합니다.") from exc
        return "자연음성 10종 설치 완료"


class NaturalTTS:
    def __init__(self, assets=None):
        self.assets = assets or NeuralModel()
        self.model = None
        self.lock = threading.Lock()

    def close(self):
        if self.lock.acquire(blocking=False):
            try:
                self.model = None
            finally:
                self.lock.release()

    def synthesize(self, text, target, voice, rate, volume, cancel, progress=None):
        import numpy as np
        import soundfile as sf
        identity = voice.removeprefix(PREFIX)
        if not voice.startswith(PREFIX) or identity not in VOICE_IDS:
            raise ValueError("지원하지 않는 자연음성입니다.")
        try:
            with self.lock:
                check_cancel(cancel)
                if not self.assets.installed():
                    raise ValueError(f"자연음성 모델을 먼저 설치하세요({self.assets.size_mb}MiB). 설치 후에는 오프라인으로 사용할 수 있습니다.")
                if self.model is None:
                    if progress:
                        progress("자연음성 모델 확인·CPU 엔진 준비 중…")
                    self.assets.verify(cancel)
                    try:
                        from supertonic import TTS
                    except ImportError as exc:
                        raise RuntimeError("자연음성 엔진을 불러오지 못했습니다. requirements.txt의 supertonic·onnxruntime을 설치하거나 앱을 복구하세요.") from exc
                    self.model = TTS(model="supertonic-3", model_dir=self.assets.folder, auto_download=False,
                                     intra_op_num_threads=max(1, min(4, (os.cpu_count() or 2) - 1)), inter_op_num_threads=1)
                check_cancel(cancel)
                style = self.model.get_voice_style(identity)
                chunks = split_text(text)
                sample_rate = self.model.sample_rate
                frames = 0
                with sf.SoundFile(str(target), "w", samplerate=sample_rate, channels=1, subtype="PCM_16", format="WAV") as output:
                    for index, chunk in enumerate(chunks):
                        check_cancel(cancel)
                        if progress:
                            progress(f"자연음성 생성 중: {index + 1}/{len(chunks)} · {identity}")
                        audio, _ = self.model.synthesize(chunk, voice_style=style, lang="ko", total_steps=10,
                                                        speed=2 ** (rate / 20), max_chunk_length=120, verbose=False)
                        check_cancel(cancel)
                        if audio.ndim != 2 or audio.shape[0] != 1 or not audio.size or not np.isfinite(audio).all():
                            raise ValueError("자연음성 엔진이 유효하지 않은 음성을 생성했습니다.")
                        frames += audio.shape[1]
                        gap = int(sample_rate * .2) if index + 1 < len(chunks) else 0
                        frames += gap
                        if frames > min(sample_rate * 600, 32_000_000):
                            raise ValueError("자연음성이 처리 한도(10분 또는 3,200만 샘플)를 넘습니다. 텍스트를 나누세요.")
                        output.write(np.clip(audio.T * (volume / 100), -.98, .98))
                        if gap:
                            output.write(np.zeros((gap, 1), dtype=np.float32))
        finally:
            if cancel.is_set():
                self.close()
