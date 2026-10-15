"""One worker, bounded queue, stable-file polling; no Tk calls in workers."""
from copy import deepcopy
from pathlib import Path
import queue
import threading

from app.automation.executor import Cancelled, WorkflowExecutor
from app.automation.graph import validate
from app.automation.registry import builtin_registry
from app.automation.storage import RunLogger, WorkflowStore


class AutomationRuntime:
    def __init__(self, root, registry=None):
        self.registry = registry or builtin_registry()
        self.store = WorkflowStore(Path(root) / "workflows")
        self.logger = RunLogger(Path(root) / "runs.sqlite3")
        self.events = queue.Queue(maxsize=2000)
        self.jobs = queue.Queue(maxsize=256)
        self.lock = threading.RLock()
        self.shutdown = threading.Event()
        self.running = {}
        self.generations = {}
        self.watches = {}
        self.errors = {}
        self.threads = [threading.Thread(target=self._worker, daemon=True, name="workflow-worker"), threading.Thread(target=self._watch, daemon=True, name="workflow-watch")]
        for thread in self.threads:
            thread.start()
        for workflow in self.store.list():
            if workflow.get("enabled") is True:
                try:
                    self.enable(workflow)
                except (ValueError, OSError) as exc:
                    self.errors[workflow["id"]] = str(exc)
                    self.emit(workflow["id"], "error", str(exc))

    def emit(self, workflow_id, kind, message):
        try:
            self.events.put_nowait((workflow_id, kind, message))
        except queue.Full:
            pass  # Persistent run detail is independent of the bounded live feed.

    def submit(self, workflow, trigger_id, payload=None):
        errors = validate(workflow, self.registry)
        if errors:
            raise ValueError("\n".join(errors))
        with self.lock:
            if self.shutdown.is_set():
                return False
            self.generations.setdefault(workflow["id"], 0)
            try:
                self.jobs.put_nowait((deepcopy(workflow), trigger_id, payload or {}, self.generations[workflow["id"]]))
                return True
            except queue.Full:
                return False

    def _worker(self):
        while not self.shutdown.is_set():
            try:
                workflow, trigger, payload, generation = self.jobs.get(timeout=.2)
            except queue.Empty:
                continue
            wid = workflow["id"]
            cancel = threading.Event()
            with self.lock:
                if self.shutdown.is_set():
                    self.jobs.task_done()
                    break
                if generation != self.generations.get(wid, 0):
                    self.jobs.task_done()
                    continue
                self.running[wid] = cancel
            detail, run_id = [], None
            def emit(kind, message):
                detail.append(f"{message['node_id']}: {message['outputs']}" if kind == "outputs" else str(message))
                self.emit(wid, kind, message)
            try:
                run_id = self.logger.start(workflow)
                emit("status", f"실행 시작: {payload.get('file_path', workflow.get('name', wid))}")
                result = WorkflowExecutor(self.registry).execute(workflow, trigger, payload, cancel, emit)
                emit("status", f"완료 · {len(result['completed'])}개 노드 처리")
                status = "success"
            except Cancelled as exc:
                status = "cancelled"
                emit("status", str(exc))
            except Exception as exc:
                status = "failed"
                emit("error", str(exc))
            finally:
                if run_id:
                    try:
                        self.logger.finish(run_id, status, "\n".join(detail))
                    except Exception as exc:
                        self.emit(wid, "error", f"실행 기록 저장 실패: {exc}")
                with self.lock:
                    self.running.pop(wid, None)
                self.jobs.task_done()

    @staticmethod
    def _snapshot(config, excluded):
        root = Path(config["path"]).expanduser().resolve()
        if not root.is_dir():
            raise ValueError(f"감시 폴더를 찾을 수 없습니다: {root}")
        result = {}
        for path in (root.rglob("*") if config.get("recursive") else root.iterdir()):
            try:
                if path.name.startswith(".toolbox-") or any(path.resolve().is_relative_to(out) for out in excluded):
                    continue
                if path.is_file():
                    stat = path.stat()
                    result[str(path.resolve())] = (stat.st_size, stat.st_mtime_ns)
            except OSError:
                continue
        return result

    def enable(self, workflow):
        errors = validate(workflow, self.registry)
        if errors:
            raise ValueError("\n".join(errors))
        watchers = [n for n in workflow["nodes"] if n["type"] == "trigger.folder_created"]
        if not watchers:
            raise ValueError("자동 활성화에는 폴더 감시 트리거가 필요합니다.")
        excluded = [Path(n["config"]["output_dir"]).expanduser().resolve() for n in workflow["nodes"] if n["type"].startswith("file.")]
        states = []
        for node in watchers:
            root = Path(node["config"]["path"]).expanduser().resolve()
            if any(root.is_relative_to(out) for out in excluded):
                raise ValueError("출력 폴더와 감시 폴더가 겹칩니다. 별도 출력 폴더를 지정하세요.")
            initial = self._snapshot(node["config"], excluded)
            states.append({"node": node, "known": set(initial), "pending": {}, "previous": initial, "excluded": excluded})
        saved = deepcopy(workflow)
        saved["enabled"] = True
        self.store.save(saved)
        with self.lock:
            self.watches[workflow["id"]] = (saved, states)
            self.errors.pop(workflow["id"], None)

    def disable(self, workflow_id):
        with self.lock:
            self.watches.pop(workflow_id, None)
        path = self.store.path(workflow_id)
        if path.exists():
            workflow = self.store.load(path)
            workflow["enabled"] = False
            self.store.save(workflow)
        self.stop(workflow_id)

    def stop(self, workflow_id=None):
        with self.lock:
            targets = {workflow_id} if workflow_id else set(self.generations) | set(self.running) | set(self.watches)
            for wid in targets:
                self.generations[wid] = self.generations.get(wid, 0) + 1
            for wid, event in self.running.items():
                if workflow_id is None or workflow_id == wid:
                    event.set()
            # Remove pending jobs under the queue's mutex; the active worker
            # takes the same runtime lock before registering a running job.
            with self.jobs.mutex:
                kept = [job for job in self.jobs.queue if workflow_id is not None and job[0]["id"] != workflow_id]
                removed = len(self.jobs.queue) - len(kept)
                self.jobs.queue.clear()
                self.jobs.queue.extend(kept)
                self.jobs.unfinished_tasks -= removed

    def _watch(self):
        while not self.shutdown.wait(1):
            with self.lock:
                watches = list(self.watches.items())
            for wid, (workflow, states) in watches:
                for state in states:
                    try:
                        current = self._snapshot(state["node"]["config"], state["excluded"])
                        # Require two identical scans; creations, not modifications,
                        # are processed. Queue overflow is retried on the next scan.
                        state["known"].intersection_update(current)
                        for path, signature in current.items():
                            if path in state["known"]:
                                continue
                            if state["previous"].get(path) == signature:
                                with self.lock:
                                    if self.watches.get(wid, (None,))[0] is workflow and self.submit(workflow, state["node"]["id"], {"file_path": path}):
                                        state["known"].add(path)
                        state["previous"] = current
                        self.errors.pop(wid, None)
                    except Exception as exc:
                        if self.errors.get(wid) != str(exc):
                            self.errors[wid] = str(exc)
                            self.emit(wid, "error", str(exc))

    def close(self):
        self.shutdown.set()
        self.stop()
        for thread in self.threads:
            thread.join(timeout=2)
