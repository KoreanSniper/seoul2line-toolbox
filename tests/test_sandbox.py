import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.games.sandbox.model import MATERIALS, Sandbox


class SandboxTests(unittest.TestCase):
    def setUp(self):
        self.world = Sandbox(24, 20, seed=10)

    def test_falling_moves_only_once_and_conserves_particles(self):
        w = self.world
        w.put(12, 2, "sand")
        w.step()
        self.assertEqual(w.cells[3 * w.width + 12], "sand")
        for _ in range(70):
            w.step()
        self.assertEqual(w.cells.count("sand"), 1)
        self.assertIn("sand", w.cells[-w.width:])

    def test_sand_sinks_in_water_and_oil_floats(self):
        w = self.world
        for y in range(15, 20):
            for x in range(24):
                w.put(x, y, "water")
        w.put(12, 14, "sand")
        w.put(10, 14, "oil")
        for _ in range(60):
            w.step()
        self.assertIn("sand", w.cells[-24:])
        self.assertEqual(w.cells.count("water"), 120)
        self.assertEqual(w.cells.count("oil"), 1)
        self.assertLess(w.cells.index("oil") // 24, 16)

    def test_liquid_spreads_and_solid_stays(self):
        w = self.world
        for x in range(24):
            w.put(x, 19, "stone")
        w.put(12, 18, "water")
        w.step()
        self.assertEqual(w.cells.count("stone"), 24)
        self.assertNotEqual(w.cells[18 * 24 + 12], "water")

    def test_gas_rises_one_cell(self):
        w = self.world
        w.put(10, 10, "steam")
        w.step()
        self.assertEqual(w.cells[9 * 24 + 10], "steam")

    def test_freezing_melting_boiling_condensation_and_glass(self):
        for material, temperature, result in (("water", -10, "ice"), ("ice", 5, "water"),
                ("water", 105, "steam"), ("steam", 50, "water"), ("sand", 1500, "glass"),
                ("lava", 600, "stone")):
            with self.subTest(material=material):
                self.world.clear()
                self.world.put(10, 10, material)
                i = 10 * 24 + 10
                self.world.heat[i] = temperature
                self.world.step()
                self.assertEqual(self.world.cells[i], result)

    def test_heat_conduction_conserves_energy_between_solids(self):
        w = self.world
        w.put(10, 10, "metal")
        w.put(11, 10, "metal")
        i = 10 * 24 + 10
        w.heat[i] = 1000
        w.step()
        self.assertLess(w.heat[i], 1000)
        self.assertGreater(w.heat[i + 1], 20)
        self.assertAlmostEqual(w.heat[i] + w.heat[i + 1], 1020)

    def test_fire_ignites_fuel_and_water_extinguishes(self):
        for material in ("wood", "oil", "plant"):
            self.world.clear()
            self.world.put(10, 10, material)
            self.world.put(11, 10, "fire")
            self.world.step()
            self.assertEqual(self.world.cells[10 * 24 + 10], "fire")
        self.world.clear()
        self.world.put(10, 10, "fire")
        self.world.put(11, 10, "water")
        self.world.step()
        self.assertEqual(self.world.cells[10 * 24 + 10], "smoke")

    def test_lava_water_reaction(self):
        w = self.world
        w.put(10, 10, "lava")
        w.put(11, 10, "water")
        w.step()
        self.assertEqual(w.cells[10 * 24 + 10], "stone")
        self.assertEqual(w.cells[10 * 24 + 11], "steam")

    def test_blast_chain_stays_bounded_and_preserves_metal(self):
        w = self.world
        w.put(0, 0, "gunpowder")
        w.put(1, 0, "fire")
        w.put(3, 0, "gunpowder")
        w.put(4, 0, "metal")
        w.step()
        self.assertGreater(w.cells.count("fire"), 10)
        self.assertEqual(w.cells[3], "gunpowder")
        self.assertEqual(w.cells[4], "metal")
        w.step()
        self.assertNotEqual(w.cells[3], "gunpowder")
        self.assertEqual(len(w.cells), 480)

    def test_salt_dissolves_and_evaporation_leaves_salt(self):
        w = self.world
        w.put(10, 10, "salt")
        w.put(11, 10, "water")
        w.step()
        self.assertEqual(w.cells.count("saltwater"), 1)
        self.assertEqual(w.cells.count("salt"), 0)
        i = w.cells.index("saltwater")
        w.heat[i] = 110
        w.step()
        self.assertEqual(w.cells.count("steam"), 1)
        self.assertEqual(w.cells.count("salt"), 1)

    def test_acid_consumes_itself_but_glass_resists(self):
        w = self.world
        w.put(10, 10, "acid")
        w.put(11, 10, "wood")
        w.step()
        self.assertEqual(w.cells.count("acid"), 0)
        self.assertEqual(w.cells.count("wood"), 0)
        w.put(10, 10, "acid")
        w.put(11, 10, "glass")
        w.step()
        self.assertEqual(w.cells.count("glass"), 1)
        self.assertEqual(w.cells.count("acid"), 1)

    def test_spark_propagates_and_returns_to_metal(self):
        w = self.world
        for x in range(5, 18):
            w.put(x, 10, "metal")
        w.put(5, 10, "spark")
        for _ in range(4):
            w.step()
        self.assertTrue(any(w.cells[10 * 24 + x] == "spark" for x in range(6, 18)))
        for _ in range(150):
            w.step()
        self.assertEqual(w.cells.count("spark"), 0)
        self.assertEqual(w.cells.count("metal"), 13)

    def test_brush_clipping_erase_heat_and_solid_protection(self):
        w = self.world
        w.brush(0, 0, 2, "stone")
        count = w.cells.count("stone")
        self.assertGreater(count, 1)
        w.brush(0, 0, 2, "water")
        self.assertEqual(w.cells.count("stone"), count)
        w.brush(0, 0, 2, "heat")
        self.assertEqual(w.heat[0], 120)
        w.brush(0, 0, 2, "cool")
        self.assertEqual(w.heat[0], 20)
        w.brush(0, 0, 2, "empty")
        self.assertEqual(w.cells.count("stone"), 0)

    def test_atomic_save_roundtrip_and_invalid_data(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scene.json"
            self.world.demo()
            self.world.save(path)
            loaded = Sandbox.load(path)
            self.assertEqual(loaded.cells, self.world.cells)
            self.assertEqual(loaded.heat, self.world.heat)
            self.assertEqual(loaded.life, self.world.life)
            self.assertFalse(path.with_suffix(".tmp").exists())
            original = json.loads(path.read_text())
            for key, value in (("version", 99), ("width", 10000), ("width", True),
                    ("cells", []), ("cells", ["bad"] * 480), ("heat", [float("nan")] * 480),
                    ("life", [-1] * 480)):
                bad = dict(original)
                bad[key] = value
                path.write_text(json.dumps(bad))
                with self.subTest(key=key, value=str(value)[:20]), self.assertRaises(ValueError):
                    Sandbox.load(path)

    def test_many_steps_all_materials_keep_arrays_valid(self):
        w = self.world
        for n, material in enumerate(MATERIALS):
            w.put(n + 1, 8, material)
        for _ in range(150):
            w.step()
        self.assertEqual(len(w.cells), 480)
        self.assertTrue(set(w.cells) <= set(MATERIALS))
        self.assertTrue(all(-273 <= t <= 2000 for t in w.heat))

    def test_integer_temperatures_load_and_oversized_or_broken_files_fail(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "scene.json"
            self.world.put(10, 10, "metal")
            self.world.save(path)
            data = json.loads(path.read_text())
            data["heat"] = [20] * 480
            path.write_text(json.dumps(data))
            loaded = Sandbox.load(path)
            loaded.step()
            self.assertEqual(loaded.cells.count("metal"), 1)
            for invalid in ("{", "null", "[]", '{"version": true}', " " * 5_000_001):
                path.write_text(invalid)
                with self.assertRaises(ValueError):
                    Sandbox.load(path)

    def test_plant_growth_consumes_water_and_fire_smoke_expire(self):
        w = self.world
        w.put(10, 10, "plant")
        w.put(11, 10, "water")
        with patch.object(w.rng, "random", return_value=0):
            w.step()
        self.assertEqual(w.cells.count("plant"), 2)
        self.assertEqual(w.cells.count("water"), 0)
        w.clear()
        w.put(0, 0, "fire")
        w.life[0] = 1
        w.step()
        self.assertEqual(w.cells[0], "smoke")
        w.life[0] = 1
        w.step()
        self.assertEqual(w.cells[0], "empty")

    def test_closed_saltwater_keeps_salt_until_space_available(self):
        w = self.world
        i = 10 * 24 + 10
        w.put(10, 10, "saltwater")
        for y in range(9, 12):
            for x in range(9, 12):
                if (x, y) != (10, 10):
                    w.put(x, y, "glass")
                    w.heat[y * 24 + x] = 150
        w.heat[i] = 150
        w.step()
        self.assertEqual(w.cells[i], "saltwater")
        w.put(10, 9, "empty")
        w.step()
        self.assertEqual(w.cells.count("steam"), 1)
        self.assertEqual(w.cells.count("salt"), 1)

    def test_separated_wires_do_not_jump_and_metal_count_is_preserved(self):
        w = self.world
        for x in (0, 1, 2, 4, 5, 6):
            w.put(x, 0, "metal")
        w.put(0, 0, "spark")
        for _ in range(30):
            w.step()
            self.assertEqual(w.cells[4:7], ["metal"] * 3)
            self.assertEqual(w.cells.count("metal") + w.cells.count("spark"), 6)


if __name__ == "__main__":
    unittest.main()
