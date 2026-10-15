import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

from app.plugin_system import PluginManager
from app.tool_registry import ToolRegistry


class PluginInstallTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[1] / "user_data"
        test_root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="plugin-test-", dir=test_root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        config = Mock()
        config.get.return_value = {}
        self.manager = PluginManager(config, self.root)

    def archive(self, prefix="", extra=None, manifest=None):
        path = self.root / "plugin.zip"
        files = {
            prefix + "plugin.json": json.dumps(manifest or {"id": "sample", "name": "샘플"}),
            prefix + "plugin.py": "def register(registry):\n    pass\n",
            prefix + "assets/icon.txt": "asset",
        }
        files.update(extra or {})
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in files.items():
                info = zipfile.ZipInfo()
                info.filename = name  # Preserve hostile backslashes on Windows too.
                archive.writestr(info, content)
        return path

    def test_root_and_wrapped_zip_install_and_load(self):
        for prefix in ("", "sample/"):
            with self.subTest(prefix=prefix):
                manifest = {"id": "wrapped" if prefix else "root"}
                plugin = self.manager.install_zip(self.archive(prefix, manifest=manifest))
                self.assertEqual(plugin.path.parent, self.root / "user_data/plugins")
                self.assertEqual((plugin.path / "assets/icon.txt").read_text(), "asset")
        loaded = self.manager.load_into(ToolRegistry())
        self.assertEqual([item.status for item in loaded], ["활성", "활성"])

    def test_install_does_not_execute_plugin(self):
        plugin = self.manager.install_zip(self.archive(extra={"plugin.py": "raise RuntimeError('executed')"}))
        self.assertTrue(plugin.path.is_dir())
        self.assertEqual(self.manager.load_into(ToolRegistry())[0].status, "로드 실패")

    def test_duplicate_id_preserves_existing_files(self):
        plugin = self.manager.install_zip(self.archive())
        original = (plugin.path / "plugin.py").read_bytes()
        with self.assertRaisesRegex(ValueError, "이미 설치"):
            self.manager.install_zip(self.archive(extra={"plugin.py": "changed"}))
        self.assertEqual((plugin.path / "plugin.py").read_bytes(), original)

    def test_bundled_plugin_id_cannot_be_overwritten(self):
        bundled = self.root / "plugins/bundled"
        bundled.mkdir(parents=True)
        (bundled / "plugin.json").write_text('{"id": "sample"}')
        with self.assertRaisesRegex(ValueError, "이미 설치"):
            self.manager.install_zip(self.archive())

    def test_unsafe_paths_are_rejected_without_installing(self):
        for name in ("../escape.py", "/absolute.py", "C:/escape.py", "folder\\escape.py",
                     "file:stream", "CON.txt", "trailing./file", "PLUGIN.py"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.manager.install_zip(self.archive(extra={name: "unsafe"}))
        self.assertEqual(self.manager.discover(), [])
        self.assertFalse((self.root / "escape.py").exists())

    def test_symlink_is_rejected(self):
        archive_path = self.archive()
        with zipfile.ZipFile(archive_path, "a") as archive:
            info = zipfile.ZipInfo("link")
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(info, "../outside")
        with self.assertRaisesRegex(ValueError, "링크"):
            self.manager.install_zip(archive_path)

    def test_invalid_manifest_and_external_entrypoint_are_rejected(self):
        for manifest in ({"id": "../bad"}, {"id": "sample", "entrypoint": "../outside.py"}):
            with self.subTest(manifest=manifest), self.assertRaisesRegex(ValueError, "plugin.json"):
                self.manager.install_zip(self.archive(manifest=manifest))

    def test_multiple_manifests_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "하나"):
            self.manager.install_zip(self.archive(extra={"other/plugin.json": '{"id":"other"}'}))

    def test_corrupt_archive_leaves_no_installation(self):
        path = self.root / "bad.zip"
        path.write_bytes(b"not a zip")
        with self.assertRaisesRegex(ValueError, "ZIP"):
            self.manager.install_zip(path)
        self.assertEqual(self.manager.discover(), [])

    def test_partial_extraction_is_cleaned_up(self):
        path = self.archive()
        with patch("app.plugin_system.shutil.copyfileobj", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.manager.install_zip(path)
        self.assertEqual(list((self.root / "user_data").iterdir()), [])


if __name__ == "__main__":
    unittest.main()
