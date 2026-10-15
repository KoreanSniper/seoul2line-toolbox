from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from PIL import Image

from app.automation.executor import Cancelled, WorkflowExecutor
from app.automation.graph import validate
from app.automation.registry import NodeSpec, Port, builtin_registry
from app.automation.runtime import AutomationRuntime
from app.automation.storage import RunLogger, WorkflowStore
from app.automation.ui import image_example
from app.services.images import convert_image


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / "user_data"
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-test-", dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = builtin_registry()
        self.input = self.root / "input"
        self.input.mkdir()
        self.source = self.input / "sample.png"
        Image.new("RGB", (12, 12), "red").save(self.source)
        self.workflow = image_example()
        self.workflow["nodes"][0]["config"]["path"] = str(self.input)
        self.workflow["nodes"][2]["config"]["output_dir"] = str(self.root / "converted")
        self.workflow["nodes"][3]["config"]["output_dir"] = str(self.root / "done")

    def execute(self, workflow=None, path=None, cancel=None):
        return WorkflowExecutor(self.registry).execute(workflow or self.workflow, "node_1", {"file_path": str(path or self.source)}, cancel=cancel)

    def test_png_webp_move_preserves_source(self):
        self.assertEqual(validate(self.workflow, self.registry), [])
        before = self.source.read_bytes()
        result = self.execute()
        self.assertEqual(len(result["completed"]), 5)
        self.assertEqual(self.source.read_bytes(), before)
        self.assertFalse((self.root / "converted" / "sample.webp").exists())
        with Image.open(self.root / "done" / "sample.webp") as image:
            self.assertEqual(image.format, "WEBP")

    def test_no_overwrite(self):
        self.execute()
        target = self.root / "done" / "sample.webp"
        original = target.read_bytes()
        self.execute()
        self.assertEqual(target.read_bytes(), original)
        self.assertTrue(target.with_name("sample_1.webp").exists())

    def test_false_branch_skips_conversion(self):
        other = self.input / "notes.txt"
        other.write_text("data")
        result = self.execute(path=other)
        self.assertEqual(result["completed"], ["node_1", "node_2"])
        self.assertFalse((self.root / "done").exists())

    def test_cancellation(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(Cancelled):
            self.execute(cancel=cancel)
        self.assertFalse((self.root / "converted").exists())

    def test_missing_input(self):
        self.workflow["connections"] = [e for e in self.workflow["connections"] if e["to_port"] != "source_path"]
        self.assertTrue(any("필수 입력" in e for e in validate(self.workflow, self.registry)))

    def test_cycle_and_type_checks(self):
        self.workflow["connections"].append({"from_node": "node_4", "from_port": "flow", "to_node": "node_2", "to_port": "flow_in"})
        self.assertTrue(any("순환" in e for e in validate(self.workflow, self.registry)))
        self.workflow["connections"][1]["from_port"] = "flow"
        self.assertTrue(any("포트 타입" in e for e in validate(self.workflow, self.registry)))

    def test_unknown_node_preserved(self):
        self.workflow["nodes"][2]["type"] = "disabled_plugin.convert"
        self.assertTrue(any("사용 불가" in e for e in validate(self.workflow, self.registry)))
        store = WorkflowStore(self.root / "store")
        self.assertEqual(store.load(store.save(self.workflow)), self.workflow)

    def test_storage_and_path_traversal(self):
        store = WorkflowStore(self.root / "store")
        self.assertEqual(store.load(store.save(self.workflow)), self.workflow)
        with self.assertRaises(ValueError):
            store.path("../config")
        self.workflow["nodes"][0]["position"] = [float("nan"), 0]
        with self.assertRaises(ValueError):
            store.save(self.workflow)

    def test_duplicate_data_input(self):
        self.workflow["connections"].append(deepcopy(self.workflow["connections"][1]))
        self.assertTrue(any("하나의 연결" in e for e in validate(self.workflow, self.registry)))

    def test_data_requires_flow_ancestor(self):
        self.workflow["connections"] = [e for e in self.workflow["connections"] if not (e["from_node"] == "node_2" and e["from_port"] == "true")]
        self.assertTrue(any("데이터 공급자" in e for e in validate(self.workflow, self.registry)))

    def test_invalid_image_cleans_temporary_output(self):
        self.source.write_bytes(b"broken png")
        with self.assertRaises(Exception):
            self.execute()
        self.assertEqual(list((self.root / "converted").iterdir()), [])
        self.assertTrue(self.source.exists())

    def test_shared_service_preserves_existing_target_on_failure(self):
        target = self.root / "existing.webp"
        target.write_bytes(b"original")
        self.source.write_bytes(b"invalid")
        with self.assertRaises(Exception):
            convert_image(self.source, target, "webp")
        self.assertEqual(target.read_bytes(), b"original")
        self.assertEqual(list(self.root.glob(".toolbox-*")), [])

    def test_interrupted_history_recovery(self):
        path = self.root / "runs.db"
        logger = RunLogger(path)
        logger.start(self.workflow)
        self.assertEqual(RunLogger(path).recent()[0]["status"], "interrupted")

    def test_join_executes_once_and_waits_for_data(self):
        workflow = deepcopy(self.workflow)
        workflow["nodes"] = [workflow["nodes"][0], {"id": "a", "type": "output.log", "position": [0, 0], "config": {}}, {"id": "b", "type": "output.log", "position": [0, 0], "config": {}}, {"id": "join", "type": "output.log", "position": [0, 0], "config": {}}]
        workflow["connections"] = [{"from_node": a, "from_port": "flow", "to_node": b, "to_port": "flow"} for a, b in [("node_1", "a"), ("node_1", "b"), ("a", "join"), ("b", "join")]]
        result = self.execute(workflow)
        self.assertEqual(result["completed"].count("join"), 1)
        self.assertEqual(result["completed"][-1], "join")

    def test_stable_file_watch_batch_and_output_exclusion(self):
        self.workflow["nodes"][0]["config"]["recursive"] = True
        self.workflow["nodes"][2]["config"]["output_dir"] = str(self.input / "converted")
        self.workflow["nodes"][3]["config"]["output_dir"] = str(self.input / "done")
        runtime = AutomationRuntime(self.root / "automation")
        self.addCleanup(runtime.close)
        runtime.enable(self.workflow)
        # Existing sample.png is baseline, never scheduled.
        for index in range(25):
            Image.new("RGB", (8, 8), "blue").save(self.input / f"new_{index}.png")
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if len(runtime.logger.recent()) == 25 and all(r["status"] == "success" for r in runtime.logger.recent()):
                break
            time.sleep(.1)
        self.assertEqual(len(runtime.logger.recent()), 25)
        self.assertTrue(all(r["status"] == "success" for r in runtime.logger.recent()))
        self.assertEqual(len(list((self.input / "done").glob("*.webp"))), 25)
        time.sleep(2.2)
        self.assertEqual(len(runtime.logger.recent()), 25)
        runtime.disable(self.workflow["id"])
        self.assertNotIn(self.workflow["id"], runtime.watches)
        self.assertFalse(runtime.store.list()[0]["enabled"])

    def test_watch_rejects_same_output_root(self):
        runtime = AutomationRuntime(self.root / "automation")
        self.addCleanup(runtime.close)
        self.workflow["nodes"][2]["config"]["output_dir"] = str(self.input)
        with self.assertRaises(ValueError):
            runtime.enable(self.workflow)

    def test_tk_editor_and_manager_in_both_themes(self):
        import tkinter as tk
        from app.automation.ui import Editor, Manager
        from types import SimpleNamespace
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        root.automation = AutomationRuntime(self.root / "automation")
        self.addCleanup(root.automation.close)
        root.drain_automation_events = lambda: []
        for dark in (True, False):
            root.dark_mode = dark
            editor = Editor(root, root)
            editor.set_mode("advanced")
            original_count = len(editor.workflow["nodes"])
            editor.pack(fill="both", expand=True)
            root.update_idletasks()
            editor.selected = "node_2"
            editor.inspect()
            editor.condition_editor.fields["legacy_extension"]["extension"][0].set("jpg")
            editor.apply()
            self.assertEqual(editor.node()["config"]["blocks"][0]["config"]["extension"], "jpg")
            editor.undo()
            self.assertEqual(editor.workflow["nodes"][1]["config"]["blocks"][0]["config"]["extension"], "png")
            editor.redo()
            self.assertEqual(editor.workflow["nodes"][1]["config"]["blocks"][0]["config"]["extension"], "jpg")
            editor.selected = "node_2"
            editor.duplicate()
            self.assertEqual(len(editor.workflow["nodes"]), original_count + 1)
            editor.delete()
            self.assertEqual(len(editor.workflow["nodes"]), original_count)
            editor.selected = "node_1"
            editor.drag = (20, 20, 50, 100)
            editor.motion(SimpleNamespace(x=60, y=60))
            self.assertEqual(editor.node()["position"], [100, 150])
            editor.zoom(SimpleNamespace(x=60, y=60, delta=120))
            self.assertGreater(editor.scale, .8)
            editor.destroy()
            self.assertFalse(root.bind("<Control-s>"))
            root.automation.store.save(self.workflow)
            for history in (False, True):
                manager = Manager(root, root, history=history)
                manager.pack()
                root.update_idletasks()
                if not history:
                    self.assertEqual(len(manager.tree.get_children()), 1)
                manager.destroy()

    def test_stop_cancels_active_and_queued_runs(self):
        entered, release = threading.Event(), threading.Event()
        def slow(config, cancel, emit):
            entered.set()
            release.wait(4)
            return {}
        self.registry.register(NodeSpec("test.slow", "Slow", "test", {"flow": Port("Flow")}, {"flow": Port("Flow")}, handler=slow))
        workflow = {"schema_version": 1, "id": "cancel_test", "name": "Cancel", "enabled": False, "nodes": [{"id": "start", "type": "trigger.manual", "position": [0, 0], "config": {}}, {"id": "slow", "type": "test.slow", "position": [0, 0], "config": {}}], "connections": [{"from_node": "start", "from_port": "flow", "to_node": "slow", "to_port": "flow"}]}
        runtime = AutomationRuntime(self.root / "automation", self.registry)
        self.addCleanup(runtime.close)
        self.addCleanup(release.set)
        self.assertTrue(runtime.submit(workflow, "start"))
        self.assertTrue(entered.wait(3))
        self.assertTrue(runtime.submit(workflow, "start"))
        runtime.stop(workflow["id"])
        release.set()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and runtime.running:
            time.sleep(.05)
        self.assertEqual(len(runtime.logger.recent()), 1)
        self.assertEqual(runtime.logger.recent()[0]["status"], "cancelled")
        self.assertEqual(runtime.jobs.qsize(), 0)

    def test_active_watch_restored_on_restart(self):
        runtime = AutomationRuntime(self.root / "automation")
        runtime.enable(self.workflow)
        runtime.close()
        resumed = AutomationRuntime(self.root / "automation")
        self.addCleanup(resumed.close)
        self.assertIn(self.workflow["id"], resumed.watches)
        self.assertEqual(resumed.logger.recent(), [])

    def test_malformed_import_rejected(self):
        store = WorkflowStore(self.root / "store")
        self.workflow["nodes"][0]["position"] = ["bad", 0]
        path = self.root / "malformed.workflow.json"
        path.write_text(json.dumps(self.workflow), encoding="utf-8")
        with self.assertRaises(ValueError):
            store.load(path)


if __name__ == "__main__":
    unittest.main()
