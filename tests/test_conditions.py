from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from PIL import Image

from app.automation.conditions import (ConditionSpec, evaluate, input_default, migrate_workflow,
                                       update_block, validate_condition)
from app.automation.data import InputResolver, execution_signature
from app.automation.executor import Cancelled, WorkflowExecutor
from app.automation.graph import validate
from app.automation.ports import compatible
from app.automation.registry import NodeSpec, Port, builtin_registry
from app.automation.runtime import AutomationRuntime
from app.automation.storage import WorkflowStore
from app.automation.ui import Editor, image_example


def block(type_id, config=None, block_id="c1"):
    return {"id": block_id, "type": type_id, "config": config or {}}


def edge(a, b, out="flow", inp="flow"):
    return {"from_node": a, "from_port": out, "to_node": b, "to_port": inp}


class ConditionTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "user_data"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-test-", dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = builtin_registry()
        self.source = self.root / "sample.png"
        Image.new("RGB", (8, 8), "green").save(self.source)

    def workflow(self, items, expression=None):
        return {"schema_version": 1, "id": "condition_test", "name": "Condition test", "enabled": False,
                "nodes": [{"id": "start", "type": "trigger.manual", "position": [0, 0], "config": {"file_path": str(self.source)}},
                          {"id": "condition", "type": "logic.condition", "position": [0, 0], "config": {"blocks": items, "expression": expression or {"block": items[0]["id"]}}},
                          {"id": "yes", "type": "output.log", "position": [0, 0], "config": {"message": "yes"}},
                          {"id": "no", "type": "output.log", "position": [0, 0], "config": {"message": "no"}}],
                "connections": [edge("start", "condition", inp="flow_in"), edge("condition", "yes", "true"), edge("condition", "no", "false")]}

    def run_graph(self, workflow, emit=None):
        return WorkflowExecutor(self.registry).execute(workflow, "start", emit=emit)

    def eval_block(self, item):
        config = {"blocks": [item], "expression": {"block": item["id"]}}
        return evaluate(config, self.registry.conditions, lambda key: input_default(config, key, self.registry.conditions))

    def test_all_initial_condition_formats(self):
        cases = [
            ("always_true", {}, True), ("always_false", {}, False),
            ("file.extension", {"file_path": str(self.source), "extension": "PNG"}, True),
            ("file.extension", {"file_path": str(self.source), "extension": "jpg", "operator": "ne"}, True),
            ("file.exists", {"file_path": str(self.source)}, True),
            ("file.exists", {"file_path": str(self.root / "absent.png"), "operator": "missing"}, True),
            ("file.size", {"file_path": str(self.source), "threshold": self.source.stat().st_size, "operator": "le"}, True),
            ("string.compare", {"a": "abc", "b": "b", "operator": "contains"}, True),
            ("string.compare", {"a": "abc", "b": "ab", "operator": "starts_with"}, True),
            ("number.compare", {"a": 2, "b": 3, "operator": "lt"}, True),
            ("boolean.check", {"value": False, "operator": "is_false"}, True),
        ]
        for type_id, config, expected in cases:
            with self.subTest(type_id=type_id, config=config):
                self.assertEqual(self.eval_block(block(type_id, config)), expected)

    def test_dynamic_inputs_and_port_policies(self):
        for type_id, expected in [("always_true", {}), ("file.extension", {"file_path": "FilePath"}),
                                  ("number.compare", {"a": "Number", "b": "Number"}),
                                  ("file.size", {"file_path": "FilePath", "threshold": "Number"})]:
            node = self.workflow([block(type_id)])["nodes"][1]
            inputs = self.registry.inputs_for(node)
            self.assertTrue(inputs.pop("flow_in").allows_multiple)
            self.assertEqual({k: p.type for k, p in inputs.items()}, {f"c1.{k}": v for k, v in expected.items()})
            self.assertTrue(all(not p.allows_multiple for p in inputs.values()))
        self.assertTrue(Port("FileList").allows_multiple)
        self.assertTrue(compatible(Port("FilePath"), Port("FileList")))
        self.assertFalse(compatible(Port("String"), Port("Number")))

    def test_connected_path_overrides_missing_or_stale_manual_value(self):
        for settings in ({}, {"file_path": str(self.root / "wrong.jpg")}):
            workflow = self.workflow([block("file.extension", settings)])
            workflow["connections"].append(edge("start", "condition", "file_path", "c1.file_path"))
            self.assertEqual(validate(workflow, self.registry), [])
            result = self.run_graph(workflow)
            self.assertIn("yes", result["completed"])
            self.assertNotIn("no", result["completed"])

    def test_manual_defaults_and_zero_false_empty_values_are_valid(self):
        for item in [block("number.compare", {"a": 0, "b": 0}), block("boolean.check", {"value": False}),
                     block("string.compare", {"a": "", "b": ""})]:
            workflow = self.workflow([item])
            self.assertEqual(validate(workflow, self.registry), [])
            self.run_graph(workflow)
        self.assertEqual(validate(self.workflow([block("file.extension")]), self.registry)[0].split(": ")[-1], "필수 입력 c1.file_path가 없습니다.")

    def test_and_or_not_and_nested_trees(self):
        items = [block("always_true", block_id="t"), block("always_false", block_id="f")]
        t, f = {"block": "t"}, {"block": "f"}
        cases = [({"op": "and", "children": [t, f]}, False), ({"op": "or", "children": [t, f]}, True),
                 ({"op": "not", "children": [f]}, True),
                 ({"op": "and", "children": [t, {"op": "not", "children": [{"op": "or", "children": [f, f]}]}]}, True)]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                result = self.run_graph(self.workflow(items, expression))
                self.assertEqual(result["outputs"]["condition"]["result"], expected)
                self.assertIn("yes" if expected else "no", result["completed"])
                self.assertNotIn("no" if expected else "yes", result["completed"])

    def test_short_circuit_never_reads_unused_inputs(self):
        for first, op in [("always_false", "and"), ("always_true", "or")]:
            config = {"blocks": [block(first, block_id="first"), block("file.size", block_id="unused")],
                      "expression": {"op": op, "children": [{"block": "first"}, {"block": "unused"}]}}
            with self.subTest(op=op):
                def forbidden(_):
                    self.fail("Skipped condition inputs were queried")
                self.assertEqual(evaluate(config, self.registry.conditions, forbidden), op == "or")

    def test_short_circuit_allows_inactive_connected_producer(self):
        items = [block("always_true", block_id="t"), block("number.compare", block_id="n")]
        workflow = self.workflow(items, {"op": "or", "children": [{"block": "t"}, {"block": "n"}]})
        self.registry.register(NodeSpec("test.number", "Number", "test", {"flow": Port("Flow")}, {"flow": Port("Flow"), "value": Port("Number")}, handler=lambda c, cancel, emit: {"value": 1}))
        workflow["nodes"] += [
            {"id": "gate", "type": "logic.condition", "position": [0, 0], "config": {"blocks": [block("always_false")], "expression": {"block": "c1"}}},
            {"id": "producer", "type": "test.number", "position": [0, 0], "config": {}}]
        workflow["connections"] += [edge("start", "gate", inp="flow_in"), edge("gate", "producer", "true"),
                                    edge("producer", "condition", inp="flow_in"), edge("producer", "condition", "value", "n.a")]
        self.assertEqual(validate(workflow, self.registry), [])
        result = self.run_graph(workflow)
        self.assertNotIn("producer", result["completed"])
        self.assertIn("yes", result["completed"])
        workflow["nodes"][1]["config"]["expression"]["op"] = "and"
        with self.assertRaisesRegex(ValueError, "실행되지 않은 분기"):
            self.run_graph(workflow)

    def test_connected_typed_values_and_runtime_type_error(self):
        self.registry.register(NodeSpec("test.number", "Number", "test", {"flow": Port("Flow")}, {"flow": Port("Flow"), "value": Port("Number")}, handler=lambda c, cancel, emit: {"value": 12}))
        workflow = self.workflow([block("number.compare", {"b": 10, "operator": "gt"})])
        workflow["nodes"].append({"id": "producer", "type": "test.number", "position": [0, 0], "config": {}})
        workflow["connections"] = [edge("start", "producer"), edge("producer", "condition", inp="flow_in"), *workflow["connections"][1:], edge("producer", "condition", "value", "c1.a")]
        self.assertIn("yes", self.run_graph(workflow)["completed"])
        bad = NodeSpec("test.bad", "Bad", "test", {"flow": Port("Flow")}, {"flow": Port("Flow"), "value": Port("Number")}, handler=lambda c, cancel, emit: {"value": True})
        self.registry.register(bad)
        workflow["nodes"][-1]["type"] = "test.bad"
        with self.assertRaisesRegex(ValueError, "출력 타입"):
            self.run_graph(workflow)

    def test_invalid_manual_types_and_operators(self):
        for item in [block("number.compare", {"a": True}), block("number.compare", {"a": "1"}),
                     block("boolean.check", {"value": "false"}), block("string.compare", {"a": 1}),
                     block("number.compare", {"operator": "contains"})]:
            with self.subTest(item=item):
                self.assertTrue(validate(self.workflow([item]), self.registry))
                with self.assertRaises(ValueError):
                    self.run_graph(self.workflow([item]))

    def test_single_input_rejects_multiple_and_mismatched_types(self):
        workflow = self.workflow([block("file.extension")])
        workflow["connections"] += [edge("start", "condition", "file_path", "c1.file_path")] * 2
        self.assertTrue(any("하나의 연결" in e for e in validate(workflow, self.registry)))
        workflow = self.workflow([block("number.compare")])
        workflow["connections"].append(edge("start", "condition", "file_path", "c1.a"))
        self.assertTrue(any("포트 타입" in e for e in validate(workflow, self.registry)))

    def test_filelist_connections_flatten_in_connection_order(self):
        self.registry.register(NodeSpec("test.files", "Files", "test", {"flow": Port("Flow")}, {"flow": Port("Flow"), "files": Port("FileList")}, handler=lambda c, cancel, emit: {"files": ["b.png", "c.png"]}))
        workflow = self.workflow([block("always_true")])
        workflow["nodes"] = [workflow["nodes"][0], {"id": "list", "type": "test.files", "position": [0, 0], "config": {}}, {"id": "join", "type": "data.files", "position": [0, 0], "config": {"files": ["manual-ignored.png"]}}]
        workflow["connections"] = [edge("start", "list"), edge("start", "join"), edge("list", "join"),
                                   edge("list", "join", "files", "files"), edge("start", "join", "file_path", "files")]
        self.assertEqual(validate(workflow, self.registry), [])
        result = self.run_graph(workflow)
        self.assertEqual(result["completed"], ["start", "list", "join"])
        self.assertEqual(result["outputs"]["join"]["files"], ["b.png", "c.png", str(self.source)])
        self.assertEqual(result["completed"].count("join"), 1)

    def test_type_change_preserves_compatible_port_and_manual_setting(self):
        workflow = self.workflow([block("file.extension", {"file_path": str(self.source)})])
        workflow["connections"].append(edge("start", "condition", "file_path", "c1.file_path"))
        updated, removed = update_block(workflow, "condition", "c1", "file.size", self.registry)
        self.assertFalse(removed)
        self.assertEqual(len(updated["connections"]), len(workflow["connections"]))
        self.assertEqual(updated["nodes"][1]["config"]["blocks"][0]["config"]["file_path"], str(self.source))
        self.assertIn("c1.threshold", self.registry.inputs_for(updated["nodes"][1]))
        self.assertEqual(workflow["nodes"][1]["config"]["blocks"][0]["type"], "file.extension")

    def test_type_change_removes_only_incompatible_connections(self):
        workflow = self.workflow([block("file.extension"), block("file.exists", block_id="keep")])
        workflow["connections"] += [edge("start", "condition", "file_path", "c1.file_path"), edge("start", "condition", "file_path", "keep.file_path")]
        updated, removed = update_block(workflow, "condition", "c1", "number.compare", self.registry)
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]["to_port"], "c1.file_path")
        self.assertIn("c1.a", self.registry.inputs_for(updated["nodes"][1]))
        self.assertNotIn("c1.file_path", self.registry.inputs_for(updated["nodes"][1]))
        self.assertTrue(any(e["to_port"] == "keep.file_path" for e in updated["connections"]))

    def test_legacy_migration_same_behavior_and_original_untouched(self):
        modern = image_example()
        legacy = deepcopy(modern)
        legacy["nodes"][1].update(type="logic.extension", config={"extension": "png", "source_path": str(self.source)})
        for connection in legacy["connections"]:
            if connection["to_node"] == "node_2":
                connection["to_port"] = "flow" if connection["to_port"] == "flow_in" else "source_path"
        legacy["nodes"][0]["config"]["path"] = str(self.root)
        legacy["nodes"][2]["config"]["output_dir"] = str(self.root / "converted")
        legacy["nodes"][3]["config"]["output_dir"] = str(self.root / "done")
        before = deepcopy(legacy)
        store = WorkflowStore(self.root / "store")
        path = store.save(legacy)
        migrated = store.load(path)
        self.assertEqual(migrated, migrate_workflow(migrated))
        self.assertEqual(migrated["nodes"][1]["type"], "logic.condition")
        self.assertEqual(legacy, before)
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), legacy)
        self.assertEqual(validate(legacy, self.registry), [])
        result = WorkflowExecutor(self.registry).execute(legacy, "node_1", {"file_path": str(self.source)})
        self.assertEqual(len(result["completed"]), 5)
        self.assertTrue(self.source.exists())
        self.assertTrue((self.root / "done" / "sample.webp").exists())
        self.assertEqual(legacy, before)

    def test_unknown_condition_roundtrip_and_execution_activation_blocked(self):
        workflow = self.workflow([block("plugin.unknown", {"opaque": {"a": [1, 2, 3]}})])
        store = WorkflowStore(self.root / "store")
        self.assertEqual(store.load(store.save(workflow)), workflow)
        self.assertTrue(any("사용 불가 조건" in e for e in validate(workflow, self.registry)))
        with self.assertRaisesRegex(ValueError, "사용 불가 조건"):
            self.run_graph(workflow)
        runtime = AutomationRuntime(self.root / "automation")
        self.addCleanup(runtime.close)
        with self.assertRaisesRegex(ValueError, "사용 불가 조건"):
            runtime.enable(workflow)

    def test_nested_condition_roundtrip(self):
        workflow = self.workflow([block("file.extension", {"file_path": str(self.source)}, "ext"), block("file.size", {"file_path": str(self.source)}, "size")],
                                 {"op": "and", "children": [{"block": "ext"}, {"op": "not", "children": [{"op": "not", "children": [{"block": "size"}]}]}]})
        store = WorkflowStore(self.root / "store")
        restored = store.load(store.save(workflow))
        self.assertEqual(restored, workflow)
        self.assertIn("yes", self.run_graph(restored)["completed"])

    def test_condition_registry_extension_and_non_boolean_rejected(self):
        self.registry.conditions.register(ConditionSpec("custom", "Custom", {}, lambda v, c: True))
        self.assertTrue(self.eval_block(block("custom")))
        with self.assertRaises(ValueError):
            self.registry.conditions.register(ConditionSpec("custom", "Duplicate", {}, lambda v, c: True))
        self.registry.conditions.register(ConditionSpec("invalid", "Invalid", {}, lambda v, c: 1))
        with self.assertRaisesRegex(ValueError, "Boolean"):
            self.eval_block(block("invalid"))

    def test_invalid_expression_structures_and_depth_limit(self):
        for expression in [{"block": "absent"}, {"op": "not", "children": []}, {"op": "and", "children": []},
                           {"op": "not", "children": [{"block": "c1"}] * 2}, {"op": "xor", "children": [{"block": "c1"}]}]:
            self.assertTrue(validate_condition({"blocks": [block("always_true")], "expression": expression}, self.registry.conditions))
        expression = {"block": "c1"}
        for _ in range(18):
            expression = {"op": "not", "children": [expression]}
        self.assertTrue(any("중첩 제한" in e for e in validate_condition({"blocks": [block("always_true")], "expression": expression}, self.registry.conditions)))

    def test_actual_collision_path_automatically_reaches_move(self):
        workflow = image_example()
        workflow["nodes"][0]["config"]["path"] = str(self.root)
        converted, done = self.root / "converted", self.root / "done"
        converted.mkdir()
        (converted / "sample.webp").write_bytes(b"existing intermediate")
        done.mkdir()
        (done / "sample_1.webp").write_bytes(b"existing final")
        workflow["nodes"][2]["config"]["output_dir"] = str(converted)
        workflow["nodes"][3]["config"]["output_dir"] = str(done)
        workflow["nodes"][3]["config"]["source_path"] = "invalid manual path ignored"
        events = []
        result = WorkflowExecutor(self.registry).execute(workflow, "node_1", {"file_path": str(self.source)}, emit=lambda kind, message: events.append((kind, message)))
        generated = Path(result["outputs"]["node_3"]["file_path"])
        moved = Path(result["outputs"]["node_4"]["file_path"])
        self.assertEqual(generated.name, "sample_1.webp")
        self.assertEqual(moved.name, "sample_1_1.webp")
        self.assertFalse(generated.exists())
        self.assertTrue(self.source.exists())
        self.assertEqual((converted / "sample.webp").read_bytes(), b"existing intermediate")
        self.assertEqual((done / "sample_1.webp").read_bytes(), b"existing final")
        with Image.open(moved) as image:
            self.assertEqual(image.format, "WEBP")
        self.assertTrue(any(kind == "outputs" and message["outputs"].get("file_path") == str(moved) for kind, message in events))

    def test_tk_internal_editor_add_change_delete_and_preview(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        root.dark_mode = True
        root.automation = AutomationRuntime(self.root / "automation")
        self.addCleanup(root.automation.close)
        root.drain_automation_events = lambda: []
        editor = Editor(root, root)
        editor.pack()
        self.addCleanup(editor.destroy)
        editor.set_mode("advanced")
        editor.replace(self.workflow([block("file.extension")]))
        editor.workflow["connections"].append(edge("start", "condition", "file_path", "c1.file_path"))
        editor.selected = "condition"
        editor.inspect()
        editor.draw()
        self.assertNotIn("file_path", editor.condition_editor.fields["c1"])
        editor.preview_signature = execution_signature(editor.workflow)
        editor.preview_outputs = {"start": {"file_path": str(self.source)}}
        editor.condition_editor.preview()
        self.assertIn("True", editor.condition_editor.preview_text.get())
        editor.condition_editor.add_block("number.compare")
        self.assertEqual(len(editor.node()["config"]["blocks"]), 2)
        second = editor.node()["config"]["blocks"][1]["id"]
        editor.condition_editor.fields[second]["a"][0].set("0")
        editor.condition_editor.fields[second]["b"][0].set("1")
        editor.apply()
        self.assertEqual(editor.node()["config"]["blocks"][1]["config"]["a"], 0)
        editor.condition_editor.wrap("not")
        self.assertEqual(editor.node()["config"]["expression"]["op"], "not")
        editor.condition_editor.unwrap()
        self.assertEqual(editor.node()["config"]["expression"]["op"], "and")
        editor.condition_editor.group_op.set("or")
        editor.condition_editor.change_group()
        self.assertEqual(editor.node()["config"]["expression"]["op"], "or")
        editor.condition_editor.wrap("not")
        with patch("app.automation.condition_ui.messagebox.showinfo") as notice:
            editor.condition_editor.change_type("c1", "always_true")
            notice.assert_called_once()
        self.assertNotIn("c1.file_path", self.registry.inputs_for(editor.node()))
        editor.condition_editor.remove_block(second)
        self.assertEqual(len(editor.node()["config"]["blocks"]), 1)
        editor.condition_editor.preview()
        self.assertIn("False", editor.condition_editor.preview_text.get())
        editor.undo()
        self.assertEqual(len(editor.workflow["nodes"][1]["config"]["blocks"]), 2)
        editor.redo()
        editor.selected = "condition"
        editor.inspect()
        editor.draw()
        self.assertIn(("condition", "in", "flow_in"), editor.ports)
        root.update_idletasks()

    def test_condition_cancellation_stops_next_internal_block(self):
        cancel = threading.Event()
        visited = []
        def stop(v, c):
            visited.append("first")
            cancel.set()
            return True
        self.registry.conditions.register(ConditionSpec("stop", "Stop", {}, stop))
        self.registry.conditions.register(ConditionSpec("next", "Next", {}, lambda v, c: visited.append("next") or True))
        workflow = self.workflow([block("stop", block_id="first"), block("next", block_id="second")],
                                 {"op": "and", "children": [{"block": "first"}, {"block": "second"}]})
        with self.assertRaises(Cancelled):
            WorkflowExecutor(self.registry).execute(workflow, "start", cancel=cancel)
        self.assertEqual(visited, ["first"])

    def test_boolean_result_connection_into_next_condition(self):
        workflow = self.workflow([block("always_true")])
        first = workflow["nodes"][1]
        first["id"] = "first"
        second = {"id": "condition", "type": "logic.condition", "position": [0, 0], "config": {"blocks": [block("boolean.check", {"value": False})], "expression": {"block": "c1"}}}
        workflow["nodes"].append(second)
        workflow["connections"][0] = edge("start", "first", inp="flow_in")
        workflow["connections"] += [edge("first", "condition", "true", "flow_in"), edge("first", "condition", "result", "c1.value")]
        self.assertEqual(validate(workflow, self.registry), [])
        self.assertIn("yes", self.run_graph(workflow)["completed"])

    def test_unknown_block_connections_survive_unrelated_format_change(self):
        workflow = self.workflow([block("always_true"), block("uninstalled.condition", {"opaque": [1, 2]}, "unknown")])
        unknown_edge = edge("start", "condition", "file_path", "unknown.path")
        workflow["connections"].append(unknown_edge)
        updated, removed = update_block(workflow, "condition", "c1", "always_false", self.registry)
        self.assertFalse(removed)
        self.assertIn(unknown_edge, updated["connections"])
        store = WorkflowStore(self.root / "store")
        self.assertEqual(store.load(store.save(updated)), updated)

    def test_legacy_passthrough_port_removed_with_incompatible_format(self):
        workflow = image_example()
        updated, removed = update_block(workflow, "node_2", "legacy_extension", "always_true", self.registry)
        self.assertNotIn("file_path", self.registry.outputs_for(updated["nodes"][1]))
        self.assertEqual({e["to_port"] for e in removed}, {"legacy_extension.file_path", "source_path"})

    def test_generic_connected_input_inspector_needs_no_manual_path(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        root.dark_mode = False
        root.automation = AutomationRuntime(self.root / "automation")
        self.addCleanup(root.automation.close)
        root.drain_automation_events = lambda: []
        editor = Editor(root, root)
        self.addCleanup(editor.destroy)
        editor.selected = "node_4"
        editor.inspect()
        self.assertNotIn("source_path", editor.fields)
        editor.fields["output_dir"].set(str(self.root / "done"))
        self.assertTrue(editor.apply())
        self.assertNotIn("source_path", editor.node()["config"])


if __name__ == "__main__":
    unittest.main()
