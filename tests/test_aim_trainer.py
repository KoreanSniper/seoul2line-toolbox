import ctypes
import gc
import math
import random
import tkinter as tk
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.games.aim_trainer.model import AimSession, Camera, Sensitivity, dot, project, ray_sphere
from app.games.aim_trainer.scene import render_faces
from app.games.aim_trainer.raw_mouse import Header, Mouse, Packet, RawMouse
from app.games.aim_trainer.view import AimTrainer
from app.palette import ThemeMode
from app.theme_art import tool_icon
from app.tool_registry import ToolRegistry
from app.tools.gaming_aim_trainer import register


class AimModelTests(unittest.TestCase):
    def test_edpi_800_and_physical_distance_independent_of_dpi(self):
        for dpi in (400, 800, 1600, 3200):
            setting = Sensitivity(dpi, .07, 103)
            self.assertEqual(setting.dpi * setting.sensitivity, 800)
            self.assertAlmostEqual(setting.angle(dpi), 56)
            self.assertAlmostEqual(setting.cm360, 360 * 2.54 / (.07 * 800))

    def test_bad_settings_rejected(self):
        for args in ((0, 1, 90), (800, 0, 90), (800, 1, 180), (math.nan, 1, 90), (800, math.inf, 90)):
            with self.assertRaises(ValueError):
                Sensitivity(*args)

    def test_projection_center_direction_and_wrap(self):
        camera = Camera((0, 0, 0), 360, 0)
        self.assertAlmostEqual(project((0, 0, 10), camera, 800, 400, 90)[0], 400)
        self.assertAlmostEqual(project((10, 0, 10), camera, 800, 400, 90)[0], 800)
        camera.yaw = 1
        self.assertLess(project((0, 0, 10), camera, 800, 400, 90)[0], 400)
        self.assertIsNone(project((0, 0, -10), camera, 800, 400, 90))

    def test_camera_rotation_basis_and_true_perspective(self):
        camera = Camera((0, 0, 0), 35, 23)
        basis = camera.basis()
        for axis in basis:
            self.assertAlmostEqual(dot(axis, axis), 1)
        self.assertAlmostEqual(dot(basis[0], basis[1]), 0)
        self.assertAlmostEqual(dot(basis[1], basis[2]), 0)
        center = project(tuple(10 * value for value in basis[2]), camera, 800, 400, 90)
        self.assertAlmostEqual(center[0], 400)
        self.assertAlmostEqual(center[1], 200)
        camera = Camera((0, 0, 0))
        near = project((1, 0, 5), camera, 800, 400, 90)[0] - 400
        far = project((1, 0, 10), camera, 800, 400, 90)[0] - 400
        self.assertAlmostEqual(near, 2 * far)
        camera.move(0, 1, .25)
        self.assertAlmostEqual(project((1, 0, 5), camera, 800, 400, 90)[0], 400)

    def test_ray_sphere_hit_miss_behind_and_inside(self):
        self.assertEqual(ray_sphere((0, 0, 0), (0, 0, 1), (0, 0, 5), 1), 4)
        self.assertIsNone(ray_sphere((0, 0, 0), (0, 0, 1), (2, 0, 5), 1))
        self.assertIsNone(ray_sphere((0, 0, 0), (0, 0, 1), (0, 0, -5), 1))
        self.assertEqual(ray_sphere((0, 0, 0), (0, 0, 1), (0, 0, 0), 1), 1)

    def test_render_clips_frustum_for_full_camera_rotation(self):
        for yaw, pitch in ((0, 0), (90, 0), (180, 0), (270, 0), (45, 80), (45, -80)):
            camera = Camera(yaw=yaw, pitch=pitch)
            faces = render_faces(camera, (0, 1.6, 5), .25, 800, 400, 90)
            self.assertTrue(faces)
            for depth, points, color in faces:
                self.assertGreaterEqual(depth, .049)
                for x, y in points:
                    self.assertTrue(-.001 <= x <= 800.001 and -.001 <= y <= 400.001)

    def test_wasd_normalizes_diagonal_and_respects_room_bounds(self):
        camera = Camera()
        start = camera.position
        camera.move(1, 1, 1)
        self.assertAlmostEqual(math.dist(start, camera.position), 4)
        camera.move(1, 0, 100)
        self.assertEqual(camera.position[2], 13.5)

    def test_targets_hits_misses_timing_and_restart(self):
        session = AimSession(30, .25, random.Random(3))
        camera = Camera()
        self.assertIsNone(session.shoot(camera, 0))
        session.start(100)
        for _ in range(40):
            x, y, z = session.target
            self.assertTrue(-4.5 <= x <= 4.5 and .7 <= y <= 3.5 and 1 <= z <= 11)
            session.spawn(100)
        session.target = (0, 1.6, 4)
        camera.yaw = 90
        self.assertFalse(session.shoot(camera, 100.1))
        camera.yaw = 0
        self.assertTrue(session.shoot(camera, 100.5))
        self.assertEqual((session.hits, session.shots, session.accuracy), (1, 2, 50))
        self.assertAlmostEqual(session.reaction_ms, 500)
        self.assertIsNone(session.shoot(camera, 130))
        session.start(150)
        self.assertEqual((session.hits, session.shots, session.reaction_ms), (0, 0, 0))


class RawInputTests(unittest.TestCase):
    def test_capture_uses_native_coordinates_and_restores_original_clip(self):
        raw = RawMouse.__new__(RawMouse)
        raw.hwnd, raw.closed, raw.clip, raw.old_proc = 7, False, None, None
        raw.user = Mock()
        raw.user.GetForegroundWindow.return_value = 200
        raw.user.GetAncestor.return_value = 200
        def client(hwnd, pointer):
            pointer._obj.right, pointer._obj.bottom = 1000, 600
            return 1
        def screen(hwnd, pointer):
            pointer._obj.x -= 1000
            pointer._obj.y += 200
            return 1
        def previous(pointer):
            pointer._obj.left, pointer._obj.top = -1920, 0
            pointer._obj.right, pointer._obj.bottom = 1920, 1080
            return 1
        rectangles = []
        def clip(pointer):
            rect = pointer._obj
            rectangles.append((rect.left, rect.top, rect.right, rect.bottom))
            return 1
        raw.user.GetClientRect.side_effect = client
        raw.user.ClientToScreen.side_effect = screen
        raw.user.GetClipCursor.side_effect = previous
        raw.user.ClipCursor.side_effect = clip
        self.assertTrue(raw.confine_center())
        self.assertTrue(raw.confine_center())
        self.assertEqual(rectangles, [(-500, 500, -499, 501)] * 2)
        raw.user.GetClipCursor.assert_called_once()
        raw.user.GetForegroundWindow.return_value = 999
        self.assertFalse(raw.confine_center())
        self.assertEqual(len(rectangles), 2)
        raw.close()
        self.assertEqual(rectangles[-1], (-1920, 0, 1920, 1080))
        raw.close()
        raw.user.RegisterRawInputDevices.assert_called_once()

    def test_native_registration_and_restore_without_cursor_capture(self):
        root = tk.Tk()
        root.withdraw()
        self.addCleanup(root.destroy)
        root.update_idletasks()
        raw = RawMouse(root.winfo_id())
        self.addCleanup(raw.close)
        self.assertIsNotNone(raw.old_proc)
        raw.close()
        raw.close()
        self.assertIsNone(raw.old_proc)

    def test_raw_packet_signed_counts_and_absolute_device_error(self):
        self.assertEqual(ctypes.sizeof(Mouse), 24)
        raw = RawMouse.__new__(RawMouse)
        raw.user = Mock()
        raw.old_proc = 123
        raw.closed = False
        raw.dx = raw.dy = 0
        raw.error = None
        def fill(handle, command, pointer, size, header_size):
            self.assertEqual(header_size, ctypes.sizeof(Header))
            packet = pointer._obj
            packet.header.kind = 0
            packet.mouse.x, packet.mouse.y = -17, 9
            return ctypes.sizeof(Packet)
        raw.user.GetRawInputData.side_effect = fill
        raw._receive(1, 0xFF, 0, 123)
        self.assertEqual(raw.take(), (-17, 9))
        self.assertEqual(raw.take(), (0, 0))
        def absolute(*args):
            count = fill(*args)
            args[2]._obj.mouse.flags = 1
            return count
        raw.user.GetRawInputData.side_effect = absolute
        raw._receive(1, 0xFF, 0, 123)
        self.assertIsNotNone(raw.error)
        self.assertEqual(raw.take(), (0, 0))


class AimUITests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.cleanup_ui)
        self.view = AimTrainer(self.root, SimpleNamespace(dark_mode=True))
        self.view.size = lambda: (800, 400)
        self.raw = SimpleNamespace(error=None, take=lambda: (0, 0), close=Mock(), confine_center=Mock(return_value=True))
        self.native = patch("app.games.aim_trainer.view.RawMouse", return_value=self.raw)
        self.native.start()
        self.addCleanup(self.native.stop)

    def cleanup_ui(self):
        if self.view.winfo_exists():
            self.view.destroy()
        self.view = None
        self.root.destroy()
        self.root = None
        gc.collect()

    def test_start_hit_stop_and_destroy_release_input_and_timer(self):
        self.view.start()
        self.assertTrue(self.view.active)
        self.assertTrue(self.view.canvas.find_withtag('world3d'))
        self.assertEqual(self.view.settings.dpi * self.view.settings.sensitivity, 800)
        self.view.session.target = (0, 1.6, 4)
        self.view.shoot()
        self.assertEqual((self.view.session.hits, self.view.session.shots), (1, 1))
        job = self.view.job
        self.view.stop()
        self.assertNotIn(job, self.root.tk.splitlist(self.root.tk.call("after", "info")))
        self.assertIsNone(self.view.raw)
        self.raw.close.assert_called_once()
        self.view.destroy()

    def test_invalid_inputs_and_input_registration_failure_do_not_start(self):
        self.view.fields["dpi"].set("nan")
        self.view.start()
        self.assertFalse(self.view.active)
        self.view.fields["dpi"].set("800")
        with patch("app.games.aim_trainer.view.RawMouse", side_effect=OSError("unavailable")):
            self.view.start()
        self.assertIn("unavailable", self.view.status.get())
        self.assertIsNone(self.view.job)

    def test_resize_and_elapsed_time_stop_session(self):
        self.view.start()
        self.view.resize()
        self.assertFalse(self.view.active)
        self.view.start()
        self.view.session.started -= 100
        self.view.tick()
        self.assertFalse(self.view.active)
        self.assertIsNone(self.view.raw)

    def test_start_remains_active_after_real_layout_updates(self):
        del self.view.size
        self.root.geometry("1000x780")
        self.view.pack(fill="both", expand=True)
        self.root.deiconify()
        self.root.update()
        before = self.view.size()
        self.view.start()
        self.view.after_cancel(self.view.job)
        self.view.job = None
        self.root.update()
        self.assertTrue(self.view.active)
        self.assertEqual(self.view.size(), before)
        self.assertIn("eDPI 800", self.view.status.get())
        self.view.stop()

    def test_foreground_loss_and_capture_error_release_input(self):
        for result in (False, OSError("capture failure")):
            self.raw.confine_center.side_effect = None
            self.raw.confine_center.return_value = True
            self.view.start()
            self.view.after_cancel(self.view.job)
            self.view.job = None
            if isinstance(result, Exception):
                self.raw.confine_center.side_effect = result
            else:
                self.raw.confine_center.return_value = result
            self.view.tick()
            self.assertFalse(self.view.active)
            self.assertIsNone(self.view.raw)
            self.assertIsNone(self.view.job)

    def test_three_themes_and_game_menu_icon(self):
        for mode in ThemeMode:
            view = AimTrainer(self.root, SimpleNamespace(dark_mode=mode))
            view.destroy()
        registry = ToolRegistry()
        register(registry)
        self.assertEqual(registry.tools_for("게임")[0].id, "gaming.aim_trainer")
        self.assertEqual(tool_icon("gaming.aim_trainer"), "crosshair")
