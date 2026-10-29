"""Offline Voice FX schema, ordered DSP and bounded, verified render cache."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time

from app.paths import data_directory


VERSION = 1
ENGINE_VERSION = "voice-fx-1-pedalboard-0.9.22"
MAX_SAMPLES = 32_000_000
MAX_SECONDS = 600

# label, minimum, maximum, default, slider resolution
EFFECTS = {
    "pitch": ("피치", {"semitones": ("음높이 (반음)", -12, 12, 0, .5)}),
    "speed": ("재생 속도", {"factor": ("배속 (배)", .5, 2, 1, .05)}),
    "formant": ("포먼트", {"semitones": ("공명 이동 (반음 상당)", -6, 6, 0, .5)}),
    "robot": ("로봇", {"frequency": ("변조 주파수 (Hz)", 30, 300, 90, 1), "mix": ("효과 비율", 0, 1, .75, .05)}),
    "radio": ("라디오 / 무전기", {"low": ("하한 (Hz)", 100, 1000, 300, 10), "high": ("상한 (Hz)", 1500, 8000, 3400, 50), "drive": ("왜곡 (dB)", 0, 18, 4, .5)}),
    "distortion": ("디스토션", {"drive": ("왜곡 (dB)", 0, 30, 8, .5), "mix": ("효과 비율", 0, 1, .4, .05)}),
    "bitcrusher": ("비트크러시", {"bits": ("비트 깊이", 4, 16, 8, 1)}),
    "chorus": ("코러스", {"rate": ("주기 (Hz)", .1, 5, .8, .1), "depth": ("깊이", 0, 1, .25, .05), "mix": ("효과 비율", 0, 1, .25, .05)}),
    "tremolo": ("떨림 (음량)", {"rate": ("주기 (Hz)", .1, 15, 5, .1), "depth": ("깊이", 0, 1, .4, .05)}),
    "reverse": ("역재생", {}),
    "echo": ("에코", {"delay": ("간격 (초)", .05, 1, .25, .01), "feedback": ("반복 비율", 0, .7, .3, .05), "mix": ("효과 비율", 0, .7, .2, .05)}),
    "reverb": ("리버브", {"room": ("공간 크기", 0, .95, .5, .05), "damping": ("고음 감쇠", 0, 1, .5, .05), "mix": ("효과 비율", 0, .7, .25, .05)}),
    "compressor": ("컴프레서", {"threshold": ("기준 (dB)", -48, 0, -20, 1), "ratio": ("압축 비율", 1, 10, 3, .5), "attack": ("반응 (ms)", 1, 100, 10, 1), "release": ("복원 (ms)", 20, 500, 100, 10)}),
    "eq": ("음색 필터 (EQ)", {"low": ("저음 (dB)", -12, 12, 0, .5), "mid": ("중음 (dB)", -12, 12, 0, .5), "high": ("고음 (dB)", -12, 12, 0, .5)}),
    "limiter": ("리미터", {"threshold": ("출력 상한 (dB)", -18, -.1, -1, .1), "release": ("복원 (ms)", 10, 500, 100, 10)}),
}


def default_settings():
    return {"version": VERSION, "enabled": False, "chain": [
        {"id": key, "enabled": False, "params": {p: spec[3] for p, spec in params.items()}}
        for key, (_, params) in EFFECTS.items()]}


def validate_settings(value):
    """Strict validation; malformed imported data never silently becomes a valid effect."""
    if not isinstance(value, dict) or value.get("version") != VERSION or type(value.get("enabled")) is not bool:
        raise ValueError("지원하지 않거나 손상된 Voice FX 설정입니다.")
    chain = value.get("chain")
    if not isinstance(chain, list) or len(chain) > len(EFFECTS):
        raise ValueError("효과 체인 형식 또는 효과 개수가 잘못되었습니다.")
    result, seen = [], set()
    for node in chain:
        if not isinstance(node, dict) or not isinstance(node.get("id"), str) or node["id"] not in EFFECTS:
            raise ValueError("존재하지 않는 음성 효과입니다.")
        key = node["id"]
        if key in seen or type(node.get("enabled")) is not bool or not isinstance(node.get("params"), dict):
            raise ValueError("효과가 중복되었거나 활성화·파라미터 형식이 잘못되었습니다.")
        seen.add(key)
        specs = EFFECTS[key][1]
        if set(node["params"]) != set(specs):
            raise ValueError(f"{EFFECTS[key][0]} 설정 항목이 잘못되었습니다.")
        params = {}
        for name, (_, low, high, _, step) in specs.items():
            number = node["params"][name]
            if type(number) not in (int, float) or not math.isfinite(number) or not low <= number <= high:
                raise ValueError(f"{EFFECTS[key][0]}의 {specs[name][0]} 값은 {low}~{high} 범위여야 합니다.")
            if key == "bitcrusher" and int(number) != number:
                raise ValueError("비트 깊이는 정수여야 합니다.")
            params[name] = number
        result.append({"id": key, "enabled": node["enabled"], "params": params})
    return {"version": VERSION, "enabled": value["enabled"], "chain": result}


def configured(**effects):
    result = default_settings()
    result["enabled"] = bool(effects)
    for node in result["chain"]:
        if node["id"] in effects:
            node["enabled"] = True
            node["params"].update(effects[node["id"]])
    return validate_settings(result)


def builtin_presets():
    definitions = [
        ("original", "원본 음성", {}),
        ("helium", "헬륨 음성", {"pitch": {"semitones": 5}, "formant": {"semitones": 2}}),
        ("bass", "저음 음성", {"pitch": {"semitones": -4}, "formant": {"semitones": -1.5}}),
        ("robot", "로봇 음성", {"robot": {}, "bitcrusher": {"bits": 10}}),
        ("radio", "라디오 음성", {"radio": {}, "compressor": {"threshold": -24, "ratio": 4}}),
        ("cave", "동굴 음성", {"echo": {"delay": .38, "feedback": .4, "mix": .2}, "reverb": {"room": .85, "mix": .4}}),
        ("monster", "괴물 음성", {"pitch": {"semitones": -6}, "formant": {"semitones": -3}, "distortion": {"drive": 10, "mix": .3}, "reverb": {"mix": .15}}),
        ("ghost", "유령 음성", {"chorus": {"mix": .35}, "echo": {"mix": .15}, "reverb": {"room": .75, "mix": .35}}),
        ("phone", "전화기 음성", {"radio": {"low": 400, "high": 3000, "drive": 0}, "compressor": {"ratio": 2}}),
    ]
    return [{"version": VERSION, "id": "builtin-" + key, "name": name, "settings": configured(**fx)} for key, name, fx in definitions]


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise RuntimeError("음성 처리를 취소했습니다.")


def atomic_copy(source, target, cancel=None):
    target = Path(target)
    fd, temporary = tempfile.mkstemp(prefix=".voice-fx-", suffix=target.suffix, dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output, open(source, "rb") as original:
            while block := original.read(1024 * 1024):
                check_cancel(cancel)
                output.write(block)
        check_cancel(cancel)
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _hash(path, cancel=None):
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while data := stream.read(1024 * 1024):
            check_cancel(cancel)
            digest.update(data)
    return digest.hexdigest()


def _formant(samples, rate, semitones, cancel):
    """Cepstral spectral-envelope warping: keeps harmonic frequencies and phase.

    This is a voice-oriented approximation, independent of pitch resampling.
    Low-quefrency liftering separates the smooth envelope from harmonic detail.
    """
    import numpy as np
    if semitones == 0:
        return samples
    size = 2 ** math.ceil(math.log2(max(512, rate * .046)))
    hop, ratio = size // 4, 2 ** (semitones / 12)
    padded = np.pad(samples, ((size, size), (0, 0)))
    output = np.zeros_like(padded)
    weight = np.zeros(len(padded), dtype=np.float32)
    window = np.hanning(size).astype(np.float32)
    bins = np.arange(size // 2 + 1)
    cutoff = max(4, int(rate / 350))
    for start in range(0, len(padded) - size + 1, hop):
        check_cancel(cancel)
        spectrum = np.fft.rfft(padded[start:start + size] * window[:, None], axis=0)
        logmag = np.log(np.maximum(np.abs(spectrum), 1e-7))
        cepstrum = np.fft.irfft(logmag, n=size, axis=0)
        cepstrum[cutoff:-cutoff] = 0
        envelope = np.fft.rfft(cepstrum, axis=0).real
        warped = np.column_stack([np.interp(bins / ratio, bins, envelope[:, c]) for c in range(samples.shape[1])])
        gain = np.exp(np.clip(warped - envelope, -3, 3))
        output[start:start + size] += np.fft.irfft(spectrum * gain, n=size, axis=0).astype(np.float32) * window[:, None]
        weight[start:start + size] += window * window
    return output[size:size + len(samples)] / np.maximum(weight[size:size + len(samples), None], 1e-8)


def _plugins(samples, rate, plugins, cancel, tail=0):
    import numpy as np
    from pedalboard import Pedalboard
    board = Pedalboard(plugins)
    if tail:
        samples = np.pad(samples, ((0, int(rate * tail)), (0, 0)))
    blocks = []
    for start in range(0, len(samples), 16384):
        check_cancel(cancel)
        block = board(np.ascontiguousarray(samples[start:start + 16384].T), rate, reset=False)
        blocks.append(block.T.copy())
    result = np.concatenate(blocks)
    if tail:
        count = min(len(result), max(1, int(.05 * rate)))
        result[-count:] *= np.linspace(1, 0, count)[:, None]
    return result


def process(samples, rate, settings, cancel=None, progress=None):
    import numpy as np
    settings = validate_settings(settings)
    check_cancel(cancel)
    if not settings["enabled"] or not any(n["enabled"] for n in settings["chain"]):
        return samples.copy()
    try:
        import pedalboard as pb
    except ImportError as exc:
        raise RuntimeError("음성 변조 라이브러리를 불러올 수 없습니다. requirements.txt의 pedalboard를 설치하거나 앱을 복구하세요.") from exc
    original_peak = float(np.max(np.abs(samples)))
    original_rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    result = samples.copy()
    for node in settings["chain"]:
        check_cancel(cancel)
        if not node["enabled"]:
            continue
        key, p = node["id"], node["params"]
        if progress:
            progress("변조 중: " + EFFECTS[key][0])
        if key in ("pitch", "speed"):
            value = p["semitones"] if key == "pitch" else p["factor"]
            if value != (0 if key == "pitch" else 1):
                result = pb.time_stretch(np.ascontiguousarray(result.T), rate,
                    stretch_factor=value if key == "speed" else 1,
                    pitch_shift_in_semitones=value if key == "pitch" else 0,
                    preserve_formants=True).T.copy()
        elif key == "formant":
            result = _formant(result, rate, p["semitones"], cancel)
        elif key == "robot":
            for start in range(0, len(result), 65536):
                check_cancel(cancel)
                count = min(65536, len(result) - start)
                carrier = np.sin((np.arange(count) + start) * (2 * np.pi * p["frequency"] / rate))
                result[start:start + count] *= (1 - p["mix"] + p["mix"] * carrier[:, None])
        elif key == "tremolo":
            phase = np.arange(len(result)) * (2 * np.pi * p["rate"] / rate)
            result *= (1 - p["depth"] * .5 * (1 - np.cos(phase[:, None])))
        elif key == "reverse":
            result = result[::-1].copy()
        elif key == "distortion":
            drive = 10 ** (p["drive"] / 20)
            result = (1 - p["mix"]) * result + p["mix"] * np.tanh(result * drive) / max(1, drive ** .5)
        elif key == "bitcrusher":
            result = _plugins(result, rate, [pb.Bitcrush(bit_depth=p["bits"])], cancel)
        elif key == "radio":
            result = _plugins(result, rate, [pb.HighpassFilter(cutoff_frequency_hz=min(p["low"], rate * .4)),
                pb.LowpassFilter(cutoff_frequency_hz=min(p["high"], rate * .45)), pb.Distortion(drive_db=p["drive"])], cancel)
        elif key == "echo":
            repeats = 1 if not p["feedback"] else math.ceil(math.log(.001) / math.log(p["feedback"]))
            tail = min(12, p["delay"] * (repeats + 1)) if p["mix"] else 0
            result = _plugins(result, rate, [pb.Delay(delay_seconds=p["delay"], feedback=p["feedback"], mix=p["mix"])], cancel, tail)
        elif key == "reverb":
            result = _plugins(result, rate, [pb.Reverb(room_size=p["room"], damping=p["damping"], wet_level=p["mix"], dry_level=1 - p["mix"])], cancel,
                              2 + 10 * p["room"] if p["mix"] else 0)
        elif key == "chorus":
            result = _plugins(result, rate, [pb.Chorus(rate_hz=p["rate"], depth=p["depth"], mix=p["mix"])], cancel, .05 if p["mix"] else 0)
        elif key == "compressor":
            result = _plugins(result, rate, [pb.Compressor(threshold_db=p["threshold"], ratio=p["ratio"], attack_ms=p["attack"], release_ms=p["release"])], cancel)
        elif key == "limiter":
            result = _plugins(result, rate, [pb.Limiter(threshold_db=p["threshold"], release_ms=p["release"])], cancel)
            result = np.clip(result, -(10 ** (p["threshold"] / 20)), 10 ** (p["threshold"] / 20))
        elif key == "eq":
            result = _plugins(result, rate, [pb.LowShelfFilter(cutoff_frequency_hz=min(250, rate * .15), gain_db=p["low"]),
                pb.PeakFilter(cutoff_frequency_hz=min(1200, rate * .25), gain_db=p["mid"]),
                pb.HighShelfFilter(cutoff_frequency_hz=min(4000, rate * .4), gain_db=p["high"])], cancel)
        if result.size > MAX_SAMPLES or len(result) > rate * MAX_SECONDS:
            raise ValueError("변조 결과가 처리 한도(10분 또는 3,200만 샘플)를 넘습니다. 텍스트를 나누세요.")
        if not np.isfinite(result).all():
            raise ValueError("음성 변조 결과에 잘못된 신호가 있습니다.")
    check_cancel(cancel)
    peak = float(np.max(np.abs(result)))
    rms = float(np.sqrt(np.mean(result.astype(np.float64) ** 2)))
    gain = min(1, .98 / max(peak, 1e-12), original_peak / max(peak, 1e-12),
               original_rms * 1.122 / max(rms, 1e-12))
    return (result * gain).astype(np.float32)


class FXRenderer:
    def __init__(self, root=None, max_bytes=256 * 1024 * 1024):
        self.folder = Path(root) if root is not None else data_directory() / "voice_fx" / "cache"
        self.max_bytes = max_bytes

    def prune(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        entries = sorted(self.folder.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        total = 0
        for path in entries:
            # Only engine-generated hash names are owned by this cache.
            if len(path.stem) != 64 or any(c not in "0123456789abcdef" for c in path.stem):
                continue
            total += path.stat().st_size
            if total > self.max_bytes or time.time() - path.stat().st_mtime > 30 * 86400:
                path.unlink(missing_ok=True)
                path.with_suffix(".json").unlink(missing_ok=True)

    def render(self, source, settings, cancel=None, progress=None, preview_seconds=None):
        import numpy as np
        import soundfile as sf
        settings = validate_settings(settings)
        check_cancel(cancel)
        source = Path(source)
        info = sf.info(str(source))
        if (info.frames <= 0 or not 8000 <= info.samplerate <= 192000 or info.channels not in (1, 2)
                or info.frames * info.channels > MAX_SAMPLES or info.duration > MAX_SECONDS):
            raise ValueError("8~192kHz 모노/스테레오, 최대 10분·3,200만 샘플의 음성을 사용하세요.")
        if preview_seconds is not None and (not isinstance(preview_seconds, (int, float)) or not 1 <= preview_seconds <= 30):
            raise ValueError("미리듣기는 1~30초 범위여야 합니다.")
        self.prune()
        identity = hashlib.sha256(json.dumps([_hash(source, cancel), settings, ENGINE_VERSION,
            info.samplerate, info.channels, preview_seconds], sort_keys=True).encode()).hexdigest()
        target = self.folder / (identity + ".wav")
        metadata = target.with_suffix(".json")
        try:
            record = json.loads(metadata.read_text(encoding="utf-8"))
            if record["sha256"] == _hash(target, cancel):
                cached = sf.info(str(target))
                if cached.frames == record["frames"] and cached.samplerate == info.samplerate and cached.channels == info.channels:
                    target.touch()
                    if progress:
                        progress("이전 변조 결과 재사용")
                    return target
        except (OSError, ValueError, KeyError, sf.LibsndfileError):
            pass
        frames = -1 if preview_seconds is None else min(info.frames, int(preview_seconds * info.samplerate))
        samples, rate = sf.read(str(source), dtype="float32", always_2d=True, frames=frames)
        if len(samples) != (info.frames if frames == -1 else frames) or not np.isfinite(samples).all():
            raise ValueError("오디오 파일이 손상되었거나 잘못된 신호가 있습니다.")
        result = process(samples, rate, settings, cancel, progress)
        fd, temporary = tempfile.mkstemp(prefix=".render-", suffix=".wav", dir=self.folder)
        os.close(fd)
        try:
            # Disabled settings are bit-exact for full WAV copies.
            if not settings["enabled"] and preview_seconds is None and source.suffix.lower() == ".wav":
                atomic_copy(source, temporary, cancel)
            else:
                sf.write(temporary, result, rate, subtype="PCM_16")
            check_cancel(cancel)
            output = sf.info(temporary)
            record = {"sha256": _hash(temporary, cancel), "frames": output.frames}
            os.replace(temporary, target)
            from app.services.voice_fx_store import atomic_json
            atomic_json(metadata, record)
            self.prune()
            return target
        finally:
            Path(temporary).unlink(missing_ok=True)
