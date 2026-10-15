from copy import deepcopy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from app.automation.executor import WorkflowExecutor
from app.automation.graph import validate
from app.automation.registry import NodeSpec, Port, builtin_registry
from app.automation.runtime import AutomationRuntime
from app.automation.smart_connections import connect_nodes, disconnect, repair_inputs
from app.automation.storage import WorkflowStore
from app.automation.ui import Editor, image_example


class SmartConnectionTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / "user_data"
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-test-", dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.registry = builtin_registry()
        self.source = self.root / "sample.png"
        Image.new("RGB", (8, 8), "blue").save(self.source)
        self.workflow = image_example(simple=True)
        self.workflow["connections"] = []
        self.workflow["nodes"][0]["config"]["path"] = str(self.root)
        self.workflow["nodes"][1]["config"] = {"blocks": [{"id": "extension", "type": "file.extension", "config": {"extension": "png"}}], "expression": {"block": "extension"}}
        self.workflow["nodes"][2]["config"]["output_dir"] = str(self.root / "converted")
        self.workflow["nodes"][3]["config"]["output_dir"] = str(self.root / "done")

    def connect_chain(self):
        workflow = self.workflow
        for source, target in (("node_1", "node_2"), ("node_2", "node_3"), ("node_3", "node_4")):
            workflow, _, _ = connect_nodes(workflow, self.registry, source, target)
        return workflow

    def editor(self):
        import tkinter as tk
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        root.dark_mode = True
        root.automation = AutomationRuntime(self.root / "automation")
        self.addCleanup(root.automation.close)
        root.drain_automation_events = lambda: []
        editor = Editor(root, root)
        self.addCleanup(editor.destroy)
        return editor

    def test_flow_adds_data_atomically_without_mutating_original(self):
        original = deepcopy(self.workflow)
        updated, added, unresolved = connect_nodes(self.workflow, self.registry, "node_1", "node_2")
        self.assertEqual(self.workflow, original)
        self.assertEqual(len(added), 2)
        self.assertEqual(added[0]["to_port"], "flow_in")
        self.assertEqual(added[1]["to_port"], "extension.file_path")
        self.assertEqual(added[1]["auto_for"], added[0])
        self.assertFalse(unresolved)
        again, changes, _ = connect_nodes(updated, self.registry, "node_1", "node_2")
        self.assertEqual(again, updated)
        self.assertEqual(changes, [])

    def test_condition_without_file_output_uses_nearest_flow_ancestor(self):
        workflow = self.connect_chain()
        binding = next(e for e in workflow["connections"] if e["to_node"] == "node_3" and e["to_port"] == "source_path")
        self.assertEqual(binding["from_node"], "node_1")
        self.assertEqual(binding["auto_for"]["from_node"], "node_2")
        self.assertEqual(validate(workflow, self.registry), [])

    def test_conversion_result_inferred_and_collision_path_used(self):
        workflow = self.connect_chain()
        converted = self.root / "converted"
        converted.mkdir()
        (converted / "sample.webp").write_bytes(b"preserve existing output")
        binding = next(e for e in workflow["connections"] if e["to_node"] == "node_4" and e["to_port"] == "source_path")
        self.assertEqual((binding["from_node"], binding["from_port"]), ("node_3", "file_path"))
        self.assertNotIn("source_path", workflow["nodes"][3]["config"])
        result = WorkflowExecutor(self.registry).execute(workflow, "node_1", {"file_path": str(self.source)})
        self.assertEqual(result["completed"], ["node_1", "node_2", "node_3", "node_4"])
        self.assertEqual(Path(result["outputs"]["node_3"]["file_path"]).name, "sample_1.webp")
        with Image.open(result["outputs"]["node_4"]["file_path"]) as image:
            self.assertEqual(image.format, "WEBP")
        self.assertTrue(self.source.exists())
        self.assertEqual((converted / "sample.webp").read_bytes(), b"preserve existing output")

    def test_explicit_single_binding_not_replaced(self):
        workflow = self.connect_chain()
        existing = next(e for e in workflow["connections"] if e["to_node"] == "node_4" and e["to_port"] == "source_path")
        existing.pop("auto_for")
        existing["from_node"] = "node_1"
        updated, changes, _ = connect_nodes(workflow, self.registry, "node_3", "node_4")
        self.assertEqual(updated, workflow)
        self.assertFalse(changes)

    def test_manual_comparison_threshold_is_preserved(self):
        condition = self.workflow["nodes"][1]
        condition["config"]["blocks"][0].update(type="file.size", config={"threshold": 512, "operator": "le"})
        self.registry.register(NodeSpec("test.info", "Info", "test", {}, {"flow": Port("Flow"), "file_path": Port("FilePath"), "size": Port("Number")}))
        self.workflow["nodes"][0]["type"] = "test.info"
        updated, added, _ = connect_nodes(self.workflow, self.registry, "node_1", "node_2")
        self.assertEqual(len(added), 2)
        self.assertFalse(any(e["to_port"] == "extension.threshold" for e in updated["connections"]))
        self.assertEqual(updated["nodes"][1]["config"]["blocks"][0]["config"]["threshold"], 512)

    def test_ambiguous_outputs_are_reported_not_guessed(self):
        self.registry.register(NodeSpec("test.ambiguous", "Ambiguous", "test", {}, {"flow": Port("Flow"), "left": Port("FilePath"), "right": Port("FilePath")}))
        self.workflow["nodes"][0]["type"] = "test.ambiguous"
        updated, added, errors = connect_nodes(self.workflow, self.registry, "node_1", "node_4")
        self.assertEqual(len(added), 1)
        self.assertEqual(len(updated["connections"]), 1)
        self.assertIn("여러 개", errors[0])

    def test_incompatible_outputs_leave_input_unbound(self):
        self.registry.register(NodeSpec("test.number", "Number", "test", {}, {"flow": Port("Flow"), "value": Port("Number")}))
        self.workflow["nodes"][0]["type"] = "test.number"
        _, added, errors = connect_nodes(self.workflow, self.registry, "node_1", "node_4")
        self.assertEqual(len(added), 1)
        self.assertIn("호환 출력 없음", errors[0])

    def test_exact_output_name_wins_among_multiple_compatible_outputs(self):
        self.registry.register(NodeSpec("test.paths", "Paths", "test", {}, {"flow": Port("Flow"), "original": Port("FilePath"), "file_path": Port("FilePath")}))
        self.workflow["nodes"][0]["type"] = "test.paths"
        _, added, errors = connect_nodes(self.workflow, self.registry, "node_1", "node_4")
        self.assertFalse(errors)
        self.assertEqual(added[1]["from_port"], "file_path")

    def test_filelist_multiple_sources_preserved_in_connection_order(self):
        self.workflow["nodes"].append({"id": "files", "type": "data.files", "position": [0, 0], "config": {}})
        workflow, _, _ = connect_nodes(self.workflow, self.registry, "node_1", "node_3")
        workflow, _, _ = connect_nodes(workflow, self.registry, "node_1", "files")
        workflow, _, _ = connect_nodes(workflow, self.registry, "node_3", "files")
        bindings = [e for e in workflow["connections"] if e["to_node"] == "files" and e["to_port"] == "files"]
        self.assertEqual([e["from_node"] for e in bindings], ["node_1", "node_3"])
        again, changes, _ = connect_nodes(workflow, self.registry, "node_3", "files")
        self.assertEqual(again, workflow)
        self.assertEqual(changes, [])

    def test_false_branch_port_is_kept_when_explicitly_selected(self):
        workflow, _, _ = connect_nodes(self.workflow, self.registry, "node_1", "node_2")
        workflow, added, _ = connect_nodes(workflow, self.registry, "node_2", "node_3", "false", "flow")
        self.assertEqual(added[0]["from_port"], "false")
        workflow["nodes"][1]["config"]["blocks"][0]["config"]["extension"] = "jpg"
        result = WorkflowExecutor(self.registry).execute({**workflow, "nodes": workflow["nodes"][:3]}, "node_1", {"file_path": str(self.source)})
        self.assertIn("node_3", result["completed"])

    def test_cycle_plan_rejected_without_partial_changes(self):
        workflow = self.connect_chain()
        before = deepcopy(workflow)
        with self.assertRaisesRegex(ValueError, "순환"):
            connect_nodes(workflow, self.registry, "node_4", "node_2")
        self.assertEqual(workflow, before)

    def test_disconnect_removes_owned_upstream_data_but_preserves_manual(self):
        workflow = self.connect_chain()
        index = next(i for i, e in enumerate(workflow["connections"]) if (e["from_node"], e["to_node"], e["to_port"]) == ("node_2", "node_3", "flow"))
        updated = disconnect(workflow, self.registry, index)
        self.assertFalse(any(e["to_node"] == "node_3" for e in updated["connections"]))
        workflow = self.connect_chain()
        binding = next(e for e in workflow["connections"] if e["to_node"] == "node_3" and e["to_port"] == "source_path")
        binding.pop("auto_for")
        updated = disconnect(workflow, self.registry, index)
        self.assertIn(binding, updated["connections"])

    def test_owned_metadata_survives_storage_roundtrip(self):
        workflow = self.connect_chain()
        store = WorkflowStore(self.root / "workflows")
        self.assertEqual(store.load(store.save(workflow)), workflow)

    def test_simple_mode_four_nodes_no_data_ports_and_switch_is_lossless(self):
        editor = self.editor()
        self.assertEqual(editor.mode.get(), "simple")
        self.assertEqual(len(editor.workflow["nodes"]), 4)
        self.assertEqual({spec.id for spec in editor.library_specs}, {"trigger.folder_created", "logic.condition", "file.convert_image", "file.move"})
        self.assertNotIn(("node_4", "in", "source_path"), editor.ports)
        editor.selected = "node_2"
        editor.inspect()
        before, history_size = deepcopy(editor.workflow), len(editor.undo_stack)
        editor.set_mode("advanced")
        self.assertIn(("node_4", "in", "source_path"), editor.ports)
        self.assertIn("output.log", {spec.id for spec in editor.library_specs})
        editor.set_mode("simple")
        self.assertEqual(editor.workflow, before)
        self.assertEqual(len(editor.undo_stack), history_size)

    def test_simple_drag_connects_both_kinds_and_undo_redo_is_one_action(self):
        editor = self.editor()
        editor.replace(self.workflow)
        before = deepcopy(editor.workflow)
        source = editor.ports[("node_1", "out", "__node__")]
        target_node = editor.workflow["nodes"][1]
        target = editor.point(target_node["position"][0] + 70, target_node["position"][1] + 20)
        editor.press(SimpleNamespace(x=source[0], y=source[1]))
        editor.motion(SimpleNamespace(x=target[0], y=target[1]))
        editor.release(SimpleNamespace(x=target[0], y=target[1]))
        self.assertEqual(len(editor.workflow["connections"]), 2)
        self.assertTrue(any("auto_for" in e for e in editor.workflow["connections"]))
        editor.undo()
        self.assertEqual(editor.workflow, before)
        editor.redo()
        self.assertEqual(len(editor.workflow["connections"]), 2)
        editor.selected_edge = 0
        editor.delete()
        self.assertEqual(editor.workflow["connections"], [])

    def test_advanced_flow_drag_also_connects_data_and_can_opt_out(self):
        editor = self.editor()
        editor.replace(self.workflow)
        editor.set_mode("advanced")
        start = editor.ports[("node_3", "out", "flow")]
        end = editor.ports[("node_4", "in", "flow")]
        editor.press(SimpleNamespace(x=start[0], y=start[1]))
        editor.release(SimpleNamespace(x=end[0], y=end[1]))
        self.assertEqual(len(editor.workflow["connections"]), 2)
        editor.undo()
        editor.smart.set(False)
        self.assertTrue(editor.connect("node_3", "node_4", "flow", "flow"))
        self.assertEqual(len(editor.workflow["connections"]), 1)

    def test_pending_simple_settings_applied_before_switch(self):
        editor = self.editor()
        editor.selected = "node_4"
        editor.inspect()
        editor.fields["output_dir"].set(str(self.root / "pending"))
        editor.set_mode("advanced")
        self.assertEqual(editor.node()["config"]["output_dir"], str(self.root / "pending"))
        self.assertNotIn("source_path", editor.fields)

    def test_complex_conditions_and_other_nodes_preserved_in_simple_mode(self):
        editor = self.editor()
        workflow = image_example()
        config = workflow["nodes"][1]["config"]
        config["blocks"].append({"id": "extra", "type": "always_false", "config": {}})
        config["expression"] = {"op": "or", "children": [config["expression"], {"block": "extra"}]}
        editor.replace(workflow)
        editor.selected = "node_2"
        editor.inspect()
        before = deepcopy(editor.workflow)
        self.assertEqual(editor.condition_editor.collect(), config)
        editor.set_mode("advanced")
        editor.set_mode("simple")
        self.assertEqual(editor.workflow, before)
        self.assertEqual(len(editor.workflow["nodes"]), 5)

    def test_simple_condition_type_change_reinfers_file_source(self):
        editor = self.editor()
        editor.selected = "node_2"
        editor.inspect()
        with patch("app.automation.simple_ui.messagebox.showinfo"):
            editor.condition_editor.change_type("always_true")
        binding = next(e for e in editor.workflow["connections"] if e["to_node"] == "node_3" and e["to_port"] == "source_path")
        self.assertEqual(binding["from_node"], "node_1")
        editor.condition_editor.change_type("file.extension")
        self.assertTrue(any(e["to_node"] == "node_2" and e["to_port"] == "legacy_extension.file_path" for e in editor.workflow["connections"]))

    def test_reverse_connection_order_repairs_downstream_inputs(self):
        editor = self.editor()
        editor.replace(self.workflow)
        editor.connect("node_3", "node_4")
        editor.connect("node_2", "node_3")
        editor.connect("node_1", "node_2")
        self.assertEqual(validate(editor.workflow, editor.runtime.registry), [])
        source = next(e for e in editor.workflow["connections"] if e["to_node"] == "node_3" and e["to_port"] == "source_path")
        self.assertEqual(source["from_node"], "node_1")

    def test_reconnecting_parent_replaces_orphaned_auto_bindings(self):
        editor = self.editor()
        editor.replace(self.connect_chain())
        editor.workflow["nodes"].append({"id": "new_watch", "type": "trigger.folder_created", "position": [0, 0], "config": {"path": str(self.root)}})
        editor.selected_edge = next(i for i, e in enumerate(editor.workflow["connections"]) if e["from_node"] == "node_1" and e["to_port"] == "flow_in")
        editor.delete()
        self.assertFalse(any(e["from_node"] == "node_1" and "auto_for" in e for e in editor.workflow["connections"]))
        editor.connect("new_watch", "node_2")
        source = next(e for e in editor.workflow["connections"] if e["to_node"] == "node_3" and e["to_port"] == "source_path")
        self.assertEqual(source["from_node"], "new_watch")

    def test_node_deletion_removes_owned_bypass_data(self):
        editor = self.editor()
        editor.replace(self.connect_chain())
        editor.selected = "node_2"
        editor.delete()
        self.assertFalse(any(e["to_node"] == "node_3" and e["to_port"] == "source_path" for e in editor.workflow["connections"]))

    def test_repair_adds_inputs_created_after_flow_connection(self):
        self.workflow["nodes"][1]["config"] = {"blocks": [{"id": "check", "type": "always_true", "config": {}}], "expression": {"block": "check"}}
        workflow, _, _ = connect_nodes(self.workflow, self.registry, "node_1", "node_2")
        workflow["nodes"][1]["config"]["blocks"][0]["type"] = "file.exists"
        repaired, added, _ = repair_inputs(workflow, self.registry)
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["to_port"], "check.file_path")
        self.assertEqual(len(repaired["connections"]), 2)


if __name__ == "__main__":
    unittest.main()
