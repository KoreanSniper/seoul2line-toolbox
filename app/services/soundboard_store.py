"""Soundboard SQLite persistence and owned-file transactions.

Uses the same additive CREATE IF NOT EXISTS policy as the stock game. No
existing application database or configuration schema is modified.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import re
import shutil
import sqlite3
import uuid

from app.paths import data_directory


class SoundboardStore:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else data_directory()
        self.folder = self.root / "soundboard"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.path = self.folder / "soundboard.db"
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS sounds (id TEXT PRIMARY KEY, title TEXT NOT NULL, path TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL, created TEXT NOT NULL, modified TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def items(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM sounds ORDER BY position, created, id")]

    def add(self):
        identity = uuid.uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("INSERT INTO sounds VALUES (?, ?, '', (SELECT COALESCE(MAX(position),-1)+1 FROM sounds), ?, ?)", (identity, "새 사운드", now, now))
        return identity

    def rename(self, identity, title):
        title = title.strip()
        if not title or len(title) > 100:
            raise ValueError("제목은 1~100자로 입력하세요.")
        with self.connect() as db:
            db.execute("UPDATE sounds SET title=?, modified=? WHERE id=?", (title, datetime.now(timezone.utc).isoformat(), identity))

    def reorder(self, identities):
        with self.connect() as db:
            current = {r[0] for r in db.execute("SELECT id FROM sounds")}
            if len(identities) != len(current) or set(identities) != current:
                raise ValueError("사운드 목록이 변경되었습니다. 다시 시도하세요.")
            db.executemany("UPDATE sounds SET position=?, modified=? WHERE id=?", [(i, datetime.now(timezone.utc).isoformat(), key) for i, key in enumerate(identities)])

    def resolve(self, relative):
        # Only files directly owned by this tool can ever be read or deleted.
        value = Path(relative)
        target = (self.root / value).resolve()
        if not relative or value.is_absolute() or target.parent != self.folder.resolve() or target.suffix.lower() not in {".mp3", ".wav", ".ogg"}:
            raise ValueError("유효하지 않은 사운드 파일 경로입니다.")
        return target

    def _cleanup(self, relative):
        if not relative:
            return
        try:
            with self.connect() as db:
                if db.execute("SELECT 1 FROM sounds WHERE path=?", (relative,)).fetchone():
                    return
            target = self.resolve(relative)
            if re.fullmatch(r"[0-9a-f]{32}", target.stem):
                target.unlink(missing_ok=True)
        except (OSError, ValueError, sqlite3.Error):
            pass  # Never turn a successful DB transaction into a failed registration.

    def register_file(self, identity, source, validate):
        source = Path(source)
        suffix = source.suffix.lower()
        if suffix not in {".mp3", ".wav", ".ogg"}:
            raise ValueError("MP3, WAV, OGG 파일을 선택하세요.")
        name = uuid.uuid4().hex
        target = self.folder / (name + suffix)
        temporary = self.folder / (name + ".tmp")
        relative = target.relative_to(self.root).as_posix()
        try:
            shutil.copyfile(source, temporary)
            validate(temporary)
            temporary.replace(target)
            with self.connect() as db:
                row = db.execute("SELECT path FROM sounds WHERE id=?", (identity,)).fetchone()
                if row is None:
                    raise ValueError("삭제된 사운드입니다.")
                old = row[0]
                db.execute("UPDATE sounds SET path=?, modified=? WHERE id=?", (relative, datetime.now(timezone.utc).isoformat(), identity))
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        self._cleanup(old)
        return relative

    def delete(self, identity):
        with self.connect() as db:
            row = db.execute("SELECT path FROM sounds WHERE id=?", (identity,)).fetchone()
            db.execute("DELETE FROM sounds WHERE id=?", (identity,))
        if row:
            self._cleanup(row[0])

    def settings(self):
        with self.connect() as db:
            values = dict(db.execute("SELECT key,value FROM settings"))
        try:
            volume = float(values.get("volume", "100"))
            if not 0 <= volume <= 100:
                volume = 100
        except (ValueError, TypeError):
            volume = 100
        try:
            outputs = json.loads(values.get("outputs", "[]"))
            self.validate_outputs(outputs, allow_empty=True)
        except (ValueError, TypeError, KeyError):
            outputs = []
        return volume, outputs

    @staticmethod
    def validate_outputs(outputs, allow_empty=False):
        if not isinstance(outputs, list) or not (0 if allow_empty else 1) <= len(outputs) <= 2:
            raise ValueError("출력 장치를 1~2개 선택하세요.")
        seen = set()
        for output in outputs:
            if not isinstance(output, dict) or not isinstance(output.get("id"), str) or not output["id"] or output["id"] in seen or not isinstance(output.get("name"), str):
                raise ValueError("중복되거나 잘못된 출력 장치입니다.")
            if not isinstance(output.get("volume"), (int, float)) or not 0 <= output["volume"] <= 100:
                raise ValueError("장치 볼륨은 0~100%입니다.")
            seen.add(output["id"])

    def save_settings(self, volume, outputs):
        self.validate_outputs(outputs)
        if not 0 <= volume <= 100:
            raise ValueError("볼륨은 0~100%입니다.")
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO settings VALUES (?,?)", [("volume", str(volume)), ("outputs", json.dumps(outputs, ensure_ascii=False))])

    def save_volume(self, volume):
        if not 0 <= volume <= 100:
            raise ValueError("볼륨은 0~100%입니다.")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO settings VALUES ('volume',?)", (str(volume),))
