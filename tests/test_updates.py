from dataclasses import replace
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from app import paths, update_service as service
from app.update_ui import UpdateController


class UpdateTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1] / "user_data"
        root.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="update-test-", dir=root)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payload = b"MZ-test-installer"
        self.url = f"https://github.com/{service.REPOSITORY}/releases/download/v2.0.2/"
        self.release = service.Release("2.0.2", self.url + service.INSTALLER_NAME,
                                       hashlib.sha256(self.payload).hexdigest(), len(self.payload), self.url)

    def metadata(self):
        release = {"tag_name": "v2.0.2", "assets": [{"name": name, "browser_download_url": self.url + name, "size": len(self.payload)}
                                                  for name in (service.INSTALLER_NAME, "update.json")]}
        manifest = {"version": "2.0.2", "installer": service.INSTALLER_NAME, "sha256": self.release.sha256, "size": len(self.payload)}
        return release, manifest

    def test_numeric_version_order_and_no_downgrade(self):
        self.assertGreater(service.version_tuple("v2.0.10"), service.version_tuple("2.0.9"))
        with self.assertRaises(ValueError):
            service.version_tuple("../../evil")
        release, _ = self.metadata()
        with patch.object(service, "read_json", return_value=release) as read:
            self.assertIsNone(service.check_latest("2.0.2"))
            self.assertIsNone(service.check_latest("3.0.0"))
            self.assertEqual(read.call_count, 2)

    def test_release_and_manifest_must_match(self):
        release, manifest = self.metadata()
        with patch.object(service, "read_json", side_effect=[release, manifest]):
            latest = service.check_latest("2.0.1")
        self.assertEqual(latest.version, "2.0.2")
        manifest["version"] = "9.0.0"
        with patch.object(service, "read_json", side_effect=[release, manifest]), self.assertRaises(ValueError):
            service.check_latest("2.0.1")

    def test_previous_versions_filter_sort_and_paginate(self):
        metadata, _ = self.metadata()
        def release(tag, **extra):
            return dict(metadata, tag_name=tag, **extra)
        first = [release("v2.0.1")] * 30
        second = [release("v2.0.2"), release("v2.0.3"), release("v2.0.4"),
                  release("v1.0.0", prerelease=True), release("v0.9.0", draft=True),
                  release("invalid"), release("v0.8.0", assets=[])]
        with patch.object(service, "read_json_value", side_effect=[first, second]) as read:
            self.assertEqual(service.previous_versions("2.0.3"), ["2.0.2", "2.0.1"])
        self.assertIn("page=2", read.call_args.args[0])

    def test_selected_old_release_is_validated_and_latest_never_downgrades(self):
        release, manifest = self.metadata()
        with patch.object(service, "read_json", side_effect=[release, manifest]):
            self.assertEqual(service.check_previous("2.0.2", "2.0.3"), replace(self.release, page_url=f"https://github.com/{service.REPOSITORY}/releases/tag/v2.0.2"))
        for version in ("2.0.3", "2.0.4", "../bad"):
            with self.assertRaises(ValueError):
                service.check_previous(version, "2.0.3")
        with patch.object(service, "read_json", return_value=dict(release, tag_name="v2.0.1")), self.assertRaises(ValueError):
            service.check_previous("2.0.2", "2.0.3")
        manifest["sha256"] = "invalid"
        with patch.object(service, "read_json", side_effect=[release, manifest]), self.assertRaises(ValueError):
            service.check_previous("2.0.2", "2.0.3")

    def test_missing_assets_and_external_url_rejected(self):
        release, manifest = self.metadata()
        release["assets"][0]["browser_download_url"] = "https://example.com/evil.exe"
        with patch.object(service, "read_json", return_value=release), self.assertRaises(ValueError):
            service.check_latest("2.0.1")
        with patch.object(service, "urllib") as request, self.assertRaises(ValueError):
            service.open_response("http://github.com/unsafe")

    def test_release_list_requests_github_json(self):
        response = Mock()
        response.geturl.return_value = f"https://api.github.com/repos/{service.REPOSITORY}/releases"
        with patch.object(service.urllib.request, "urlopen", return_value=response) as open_url:
            service.open_response(response.geturl())
        self.assertEqual(open_url.call_args.args[0].get_header("Accept"), "application/vnd.github+json")

    def test_no_release_and_prerelease_ignored(self):
        with patch.object(service, "read_json", side_effect=HTTPError(service.API_URL, 404, "not found", {}, None)):
            self.assertIsNone(service.check_latest())
        release, _ = self.metadata()
        release["prerelease"] = True
        with patch.object(service, "read_json", return_value=release):
            self.assertIsNone(service.check_latest())

    def test_verified_download_and_corrupt_data_cleanup(self):
        with patch.object(service, "open_response", return_value=io.BytesIO(self.payload)):
            output = service.download_release(self.release, self.root)
        self.assertEqual(output.read_bytes(), self.payload)
        with patch.object(service, "open_response", return_value=io.BytesIO(b"corrupt")), self.assertRaises(ValueError):
            service.download_release(self.release, self.root)
        self.assertEqual(output.read_bytes(), self.payload)
        self.assertFalse(list(self.root.glob("*.part")))

    def test_oversize_and_path_injection_never_replace_installer(self):
        with patch.object(service, "open_response", return_value=io.BytesIO(self.payload * 2)), self.assertRaises(ValueError):
            service.download_release(self.release, self.root)
        with self.assertRaises(ValueError):
            service.download_release(replace(self.release, version="../other"), self.root)
        self.assertFalse(list(self.root.iterdir()))

    def test_installer_can_only_replace_installed_app(self):
        with patch.object(service.sys, "frozen", False, create=True), self.assertRaises(ValueError):
            service.launch_installer(self.root / "setup.exe", self.release, self.root)

    def test_installed_helper_uses_quoted_argument_list_and_no_shell(self):
        bundle = self.root / "bundle/updater"
        bundle.mkdir(parents=True)
        (bundle / "install_update.ps1").write_text("# helper")
        with patch.object(service.sys, "frozen", True, create=True), patch.object(service.sys, "_MEIPASS", str(bundle.parent), create=True), patch.object(service.subprocess, "Popen") as popen:
            service.launch_installer(self.root / "space setup.exe", self.release, self.root)
        args = popen.call_args.args[0]
        self.assertIn(str(self.root / "space setup.exe"), args)
        self.assertEqual(args[args.index("-WindowStyle") + 1], "Hidden")
        self.assertNotIn("shell", popen.call_args.kwargs)

    def test_frozen_gpu_launcher_uses_packaged_entrypoint(self):
        from app.tools import chill_starsystem_gpu as gpu
        launcher = SimpleNamespace(process=None, status=Mock())
        with patch.object(gpu.sys, "frozen", True, create=True), patch.object(gpu.subprocess, "Popen") as popen:
            gpu.GpuStarSystemLauncher.launch(launcher)
        self.assertEqual(popen.call_args.args[0][1:], ["--run-gpu-stars"])

    def test_installed_data_path_and_legacy_migration_never_overwrites(self):
        installed = self.root / "installed"
        legacy = installed / "user_data"
        legacy.mkdir(parents=True)
        (legacy / "config.json").write_text('"old"')
        (legacy / "game.json").write_text('"save"')
        destination = self.root / "local/seoul2line Toolbox/user_data"
        destination.mkdir(parents=True)
        (destination / "config.json").write_text('"new"')
        with patch.object(paths.sys, "frozen", True, create=True), patch.object(paths.sys, "executable", str(installed / "app.exe")), patch.object(paths.sys, "_MEIPASS", str(installed / "_internal"), create=True), patch.dict(os.environ, {"LOCALAPPDATA": str(self.root / "local")}):
            self.assertEqual(paths.data_directory(), destination)
            paths.migrate_legacy_data(destination)
            paths.migrate_legacy_data(destination)
        self.assertEqual((destination / "config.json").read_text(), '"new"')
        self.assertEqual((destination / "game.json").read_text(), '"save"')
        self.assertTrue((legacy / "game.json").exists())


class UpdateUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.config_store = Mock()
        self.root._close_app = Mock()
        with patch("app.update_ui.sys.frozen", False, create=True):
            self.controller = UpdateController(self.root)
        self.addCleanup(self.root.destroy)
        self.addCleanup(self.controller.close)

    def test_network_failure_and_decline_keep_app_open(self):
        self.controller.events.put(("error", "offline", False))
        self.controller.poll()
        self.assertIn("offline", self.controller.status.get())
        release = SimpleNamespace(version="2.0.2")
        self.controller.events.put(("checked", release, True))
        with patch("app.update_ui.sys.frozen", True, create=True), patch("app.update_ui.messagebox.askyesno", return_value=False), patch.object(self.controller, "download") as download:
            self.controller.poll()
        download.assert_not_called()
        self.root._close_app.assert_not_called()

    def test_verified_installer_is_launched_before_app_closes(self):
        self.controller.events.put(("downloaded", (Path("installer.exe"), object()), True))
        with patch("app.update_ui.launch_installer") as launch:
            self.controller.poll()
        launch.assert_called_once()
        self.root._close_app.assert_called_once()

    def test_downgrade_decline_does_not_fetch_or_close(self):
        dialog = Mock()
        with patch("app.update_ui.messagebox.askyesno", return_value=False) as prompt, patch("app.update_ui.check_previous") as check:
            self.controller.downgrade("2.0.2", dialog)
        self.assertEqual(prompt.call_args.kwargs["default"], "no")
        self.assertIn("데이터가 사라지거나 손상", prompt.call_args.args[1])
        check.assert_not_called()
        dialog.destroy.assert_not_called()
        self.root._close_app.assert_not_called()

    def test_version_selection_contains_old_versions_and_warning(self):
        self.controller.show_previous_versions(["2.0.2", "2.0.1"])
        dialog = next(widget for widget in self.root.winfo_children() if isinstance(widget, tk.Toplevel))
        widgets = dialog.winfo_children()[0].winfo_children()
        combo = next(widget for widget in widgets if widget.winfo_class() == "TCombobox")
        self.assertEqual(combo.get(), "2.0.2")
        self.assertEqual(str(combo.cget("state")), "readonly")
        self.assertTrue(any("데이터가 사라지거나 손상" in str(widget.cget("text")) for widget in widgets if widget.winfo_class() == "TLabel"))
        dialog.destroy()

    def test_confirmed_downgrade_fetches_selected_version_in_worker(self):
        dialog = Mock()
        release = SimpleNamespace(version="2.0.2")
        with patch("app.update_ui.messagebox.askyesno", return_value=True), patch("app.update_ui.check_previous", return_value=release) as check, patch("app.update_ui.threading.Thread") as thread:
            thread.side_effect = lambda **kwargs: SimpleNamespace(start=kwargs["target"])
            self.controller.downgrade("2.0.2", dialog)
        check.assert_called_once_with("2.0.2")
        dialog.destroy.assert_called_once()
        self.assertEqual(self.controller.events.get_nowait(), ("previous", release, True))
        self.root._close_app.assert_not_called()

    def test_previous_verified_release_download_or_source_page(self):
        release = SimpleNamespace(version="2.0.2", page_url="https://github.com/example")
        self.controller.events.put(("previous", release, True))
        with patch("app.update_ui.sys.frozen", True, create=True), patch.object(self.controller, "download") as download:
            self.controller.poll()
        download.assert_called_once_with(release)
        self.controller.events.put(("previous", release, True))
        with patch("app.update_ui.sys.frozen", False, create=True), patch("app.update_ui.webbrowser.open") as browser:
            self.controller.poll()
        browser.assert_called_once_with(release.page_url)
