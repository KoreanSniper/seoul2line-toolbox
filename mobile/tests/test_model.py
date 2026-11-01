import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mobile.model import State, MENUS, TOOLS


class MobileStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'settings.json'
        self.state = State(self.path)

    def test_rank_and_reserve_later_pin(self):
        self.state.pin('menu2', 'audio')
        for _ in range(3):
            self.state.visit('audio')
        self.state.visit('pc')
        self.assertEqual(self.state.tabs()['menu1'], 'pc')
        self.assertEqual(self.state.tabs()['menu2'], 'audio')
        self.assertEqual(len(set(self.state.tabs().values())), 3)

    def test_pin_moves_without_duplicates_and_unpin_restores_ranking(self):
        self.state.pin('menu1', 'notes')
        self.state.pin('menu2', 'notes')
        self.assertNotIn('menu1', self.state.pins)
        self.state.visit('developer')
        self.assertEqual(self.state.tabs()['menu1'], 'developer')
        self.state.pins.pop('menu2')
        self.assertEqual(self.state.tabs()['menu2'], 'audio')
        with self.assertRaises(ValueError):
            self.state.pin('home', 'audio')
        with self.assertRaises(ValueError):
            self.state.pin('tool1', 'audio')

    def test_restart_persists_theme_counts_and_pins(self):
        self.state.theme = 'green'
        self.state.pin('tool1', 'scratchpad')
        self.state.visit('tts')
        self.assertTrue(self.state.save())
        restored = State(self.path)
        self.assertEqual(restored.theme, 'green')
        self.assertEqual(restored.counts, {'tts':1})
        self.assertEqual(restored.tabs()['tool1'], 'scratchpad')
        self.assertFalse(self.path.with_suffix('.tmp').exists())

    def test_malformed_settings_do_not_crash(self):
        for payload in ('{', '[]', '{"theme":[], "pins":false,"counts":[]}',
                        '{"pins":{"menu1":[],"menu2":"missing"},"counts":{"tts":true}}'):
            self.path.write_text(payload, encoding='utf-8')
            state = State(self.path)
            self.assertEqual(state.theme, 'dark')
            self.assertEqual(state.counts, {})
            self.assertEqual(state.pins, {})

    def test_search_korean_english_description_and_empty(self):
        self.assertEqual(self.state.search('메모'), ['scratchpad'])
        self.assertEqual(self.state.search(' BASE64 '), ['converter'])
        self.assertEqual(self.state.search('TTS'), ['tts'])
        self.assertEqual(self.state.search('없는도구'), [])
        self.assertEqual(len(self.state.search('')), len(TOOLS))

    def test_write_failure_keeps_original_file(self):
        self.assertTrue(self.state.save())
        original = self.path.read_bytes()
        self.path.with_suffix('.tmp').mkdir()
        self.state.theme = 'light'
        self.assertFalse(self.state.save())
        self.assertEqual(self.path.read_bytes(), original)

    def test_unknown_values_and_duplicate_pins_are_filtered(self):
        self.path.write_text(json.dumps(dict(theme='unknown', counts={'audio':-1,'tts':4,'bad':9},
                                            pins={'menu1':'pc','menu2':'pc','tool1':'tts'})), encoding='utf-8')
        state = State(self.path)
        self.assertEqual(state.counts, {'tts':4})
        self.assertEqual(state.pins, {'menu1':'pc','tool1':'tts'})
        for slot, value in state.tabs().items():
            self.assertIn(value, TOOLS if slot == 'tool1' else MENUS)

    def test_unreadable_settings_block_save_until_explicit_backed_up_reset(self):
        self.path.write_bytes(b'\xffbroken')
        state = State(self.path)
        self.assertFalse(state.readable)
        self.assertFalse(state.save())
        self.assertEqual(self.path.read_bytes(), b'\xffbroken')
        self.assertTrue(state.reset())
        backups = list(self.path.parent.glob('settings.before-reset-*.json'))
        self.assertEqual(len(backups),1)
        self.assertEqual(backups[0].read_bytes(),b'\xffbroken')
        self.assertTrue(State(self.path).readable)

    def test_settings_backup_failure_prevents_reset(self):
        self.path.write_text('broken',encoding='utf-8')
        state = State(self.path)
        with patch('mobile.model.shutil.copyfile',side_effect=OSError('disk')):
            self.assertFalse(state.reset())
        self.assertFalse(state.readable)
        self.assertEqual(self.path.read_text(encoding='utf-8'),'broken')

    def test_oversized_settings_are_not_loaded_or_overwritten(self):
        self.path.write_bytes(b' '*262_145)
        state = State(self.path)
        self.assertFalse(state.readable)
        self.assertFalse(state.save())
        self.assertEqual(self.path.stat().st_size,262_145)


if __name__ == '__main__':
    unittest.main()
