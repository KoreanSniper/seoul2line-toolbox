from pathlib import Path
import os
import tempfile
from app.file_ops import retry_on_windows_lock


def convert_image(source: Path, target: Path, target_ext: str) -> None:
    """Preserve the source and publish only a completely encoded image."""
    from PIL import Image
    if source.suffix.lower() in {".svg", ".heic", ".heif"} or target_ext in {"svg", "heic", "heif"}:
        raise RuntimeError("SVG/HEIC 변환에는 별도 코덱 또는 ImageMagick이 필요합니다.")
    if source.resolve() == target.resolve():
        raise ValueError("원본과 출력 경로가 같습니다.")
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".toolbox-", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        with Image.open(source) as image:
            if target_ext in {"jpg", "jpeg"}:
                image = image.convert("RGB")
            image.save(temporary, format={"jpg": "JPEG", "jpeg": "JPEG", "tif": "TIFF", "ico": "ICO"}.get(target_ext, target_ext.upper()))
        retry_on_windows_lock(os.replace, temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
