"""Versioned user presets shared by TTS and the soundboard; atomic writes."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import uuid

from app.paths import data_directory
from app.services.voice_fx import VERSION, builtin_presets, validate_settings


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".preset-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path):
    path = Path(path)
    if path.stat().st_size > 512 * 1024:
        raise ValueError("프리셋 파일이 너무 큽니다(최대 512KiB).")
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("프리셋 JSON 파일이 손상되었습니다. 원본 파일은 보존했습니다.") from exc


def validate_preset(record):
    if not isinstance(record, dict) or record.get("version") != VERSION:
        raise ValueError("지원하지 않는 프리셋 버전입니다.")
    name, identity = record.get("name"), record.get("id")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 60:
        raise ValueError("프리셋 이름은 1~60자로 입력하세요.")
    if not isinstance(identity, str) or not identity or len(identity) > 80:
        raise ValueError("프리셋 식별자가 잘못되었습니다.")
    return {"version": VERSION, "id": identity, "name": name.strip(), "settings": validate_settings(record.get("settings"))}


class PresetStore:
    def __init__(self, root=None):
        self.folder = Path(root) if root is not None else data_directory() / "voice_fx"
        self.path = self.folder / "presets.json"

    def users(self):
        if not self.path.exists():
            return []
        data = read_json(self.path)
        if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("presets"), list) or len(data["presets"]) > 100:
            raise ValueError("사용자 프리셋 파일 형식이 잘못되었습니다. 기존 파일을 보존했습니다.")
        records = [validate_preset(p) for p in data["presets"]]
        if any(p["id"].startswith("builtin-") for p in records) or len({p["id"] for p in records}) != len(records):
            raise ValueError("기본 프리셋 식별자 충돌 또는 중복 프리셋입니다.")
        return records

    def all(self):
        return builtin_presets() + self.users()

    def _write(self, records):
        if len(records) > 100:
            raise ValueError("사용자 프리셋은 최대 100개까지 저장할 수 있습니다.")
        atomic_json(self.path, {"version": VERSION, "presets": records})

    def save(self, name, settings, identity=None):
        if identity and identity.startswith("builtin-"):
            raise ValueError("기본 프리셋은 수정할 수 없습니다. 새 이름으로 저장하세요.")
        records = self.users()
        if identity and not any(p["id"] == identity for p in records):
            raise ValueError("수정할 사용자 프리셋이 없습니다.")
        record = validate_preset({"version": VERSION, "id": identity or uuid.uuid4().hex, "name": name, "settings": settings})
        if any(p["name"].casefold() == record["name"].casefold() and p["id"] != record["id"] for p in self.all()):
            raise ValueError("같은 이름의 프리셋이 있습니다. 다른 이름을 사용하세요.")
        records = [record if p["id"] == identity else p for p in records] if identity else records + [record]
        self._write(records)
        return record

    def delete(self, identity):
        if identity.startswith("builtin-"):
            raise ValueError("기본 프리셋은 삭제할 수 없습니다.")
        records = self.users()
        if not any(p["id"] == identity for p in records):
            raise ValueError("삭제할 사용자 프리셋이 없습니다.")
        self._write([p for p in records if p["id"] != identity])

    def export(self, path, record):
        atomic_json(path, {"version": VERSION, "presets": [validate_preset(record)]})

    def import_file(self, path):
        data = read_json(path)
        if not isinstance(data, dict) or data.get("version") != VERSION or not isinstance(data.get("presets"), list) or not 1 <= len(data["presets"]) <= 100:
            raise ValueError("지원하지 않는 프리셋 가져오기 형식입니다.")
        imported = [validate_preset(p) for p in data["presets"]]
        records = self.users()
        names = {p["name"].casefold() for p in self.all()}
        for record in imported:
            base, count = record["name"], 1
            while record["name"].casefold() in names:
                record["name"] = base[:48] + f" (가져옴 {count})"
                count += 1
            names.add(record["name"].casefold())
            record["id"] = uuid.uuid4().hex
            records.append(record)
        self._write(records)
        return deepcopy(imported)

    def save_current(self, settings):
        atomic_json(self.folder / "current.json", validate_settings(settings))

    def current(self):
        path = self.folder / "current.json"
        return validate_settings(read_json(path)) if path.exists() else None
