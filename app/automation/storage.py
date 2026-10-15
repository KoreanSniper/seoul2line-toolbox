import json
import math
import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from app.automation.conditions import migrate_workflow


def new_workflow():
    return {"schema_version": 1, "id": uuid.uuid4().hex, "name": "새 워크플로", "enabled": False, "nodes": [], "connections": []}


class WorkflowStore:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, workflow_id):
        if not isinstance(workflow_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", workflow_id):
            raise ValueError("잘못된 워크플로 ID입니다.")
        return self.root / f"{workflow_id}.workflow.json"

    def save(self, workflow):
        target = self.path(workflow["id"])
        fd, tmp = tempfile.mkstemp(dir=self.root, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(workflow, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp, target)
        finally:
            Path(tmp).unlink(missing_ok=True)
        return target

    def load(self, path):
        if Path(path).stat().st_size > 2_000_000:
            raise ValueError("워크플로 파일은 2MB 이하만 허용됩니다.")
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("지원하지 않는 워크플로 형식입니다.")
        self.path(data.get("id"))
        if not isinstance(data.get("nodes"), list) or not isinstance(data.get("connections"), list):
            raise ValueError("노드와 연결 목록이 필요합니다.")
        if len(data["nodes"]) > 200 or len(data["connections"]) > 2000:
            raise ValueError("노드 또는 연결 수 제한을 초과했습니다.")
        seen = set()
        for node in data["nodes"]:
            if not isinstance(node, dict) or not isinstance(node.get("id"), str) or not isinstance(node.get("type"), str) or not isinstance(node.get("config", {}), dict):
                raise ValueError("잘못된 노드 구조입니다.")
            if node["id"] in seen:
                raise ValueError("중복 노드 ID입니다.")
            seen.add(node["id"])
            if node["type"] == "logic.condition":
                items = node.get("config", {}).get("blocks", [])
                if not isinstance(items, list) or len(items) > 64 or any(not isinstance(b, dict) or not isinstance(b.get("id"), str) or not isinstance(b.get("config", {}), dict) for b in items):
                    raise ValueError("잘못된 내부 조건 블록 구조입니다.")
            position = node.get("position", [0, 0])
            if not isinstance(position, list) or len(position) != 2 or any(not isinstance(v, (int, float)) or not math.isfinite(v) for v in position):
                raise ValueError("잘못된 노드 위치입니다.")
        for edge in data["connections"]:
            if not isinstance(edge, dict) or any(not isinstance(edge.get(k), str) for k in ("from_node", "from_port", "to_node", "to_port")):
                raise ValueError("잘못된 연결 구조입니다.")
        return migrate_workflow(data)

    def list(self):
        result = []
        for path in sorted(self.root.glob("*.workflow.json")):
            try:
                result.append(self.load(path))
            except (ValueError, OSError):
                continue
        return result


class RunLogger:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, workflow_id TEXT, name TEXT, started TEXT, finished TEXT, status TEXT, detail TEXT)")
            db.execute("UPDATE runs SET status='interrupted', finished=?, detail='앱 종료로 중단됨. 자동 재실행하지 않습니다.' WHERE status='running'", (self.now(),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def now():
        return datetime.now(timezone.utc).isoformat()

    def start(self, workflow):
        run_id = uuid.uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO runs VALUES (?, ?, ?, ?, NULL, 'running', '')", (run_id, workflow["id"], workflow.get("name", ""), self.now()))
        return run_id

    def finish(self, run_id, status, detail):
        with self.connect() as db:
            db.execute("UPDATE runs SET finished=?, status=?, detail=? WHERE id=?", (self.now(), status, detail, run_id))

    def recent(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute("SELECT * FROM runs ORDER BY started DESC LIMIT 300")]
