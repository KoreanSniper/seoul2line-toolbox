from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.config import AppConfig, _normalise_config
from app.palette import THEME_SWATCHES, ThemeMode, palette


def contrast(first, second):
    def luminance(color):
        rgb = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4
                  for channel in rgb]
        return sum(channel * weight for channel, weight in zip(linear, (.2126, .7152, .0722)))
    values = sorted((luminance(first), luminance(second)))
    return (values[1] + .05) / (values[0] + .05)


class PaletteTests(unittest.TestCase):
    def test_modes_keep_reference_swatches_and_support_legacy_booleans(self):
        for mode in ThemeMode:
            with self.subTest(theme=mode.value):
                colors = palette(mode)
                requested = {color.lower() for color in THEME_SWATCHES[mode.value]}
                self.assertEqual(len(requested), 10)
                for color in colors.values():
                    self.assertRegex(color, r"^#[0-9a-fA-F]{6}$")
                self.assertEqual(colors, palette(mode.value))
        self.assertEqual(palette(True), palette("dark"))
        self.assertEqual(palette(False), palette("light"))
        self.assertTrue(ThemeMode.DARK)
        self.assertFalse(ThemeMode.LIGHT)
        self.assertFalse(ThemeMode.GREEN)

    def test_text_and_selected_controls_have_readable_contrast(self):
        for mode in ThemeMode:
            colors = palette(mode)
            pairs = [("text", background) for background in
                     ("app", "panel", "panel_soft", "surface", "surface_hover", "field", "nav")]
            pairs += [("muted", "panel"), ("subtle", "field"), ("accent", "accent_soft"),
                      ("accent_text", "accent"), ("sidebar_text", "sidebar"),
                      ("sidebar_muted", "sidebar")]
            for foreground, background in pairs:
                with self.subTest(theme=mode.value, foreground=foreground, background=background):
                    self.assertGreaterEqual(contrast(colors[foreground], colors[background]), 4.5)

    def test_green_setting_survives_save_and_reload(self):
        data_root = Path(__file__).resolve().parents[1] / "user_data"
        data_root.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=data_root, prefix="palette-test-") as directory:
            root = Path(directory)
            with patch("app.config.APP_DIR", root), patch("app.config.CONFIG_PATH", root / "config.json"):
                config = AppConfig.load()
                config.set("theme", value="green")
                self.assertEqual(AppConfig.load().get("theme"), "green")
        self.assertEqual(_normalise_config({"theme": "invalid"})["theme"], "dark")


if __name__ == "__main__":
    unittest.main()
