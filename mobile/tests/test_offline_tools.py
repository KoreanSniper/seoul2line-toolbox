from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from mobile.offline_tools import (format_json, encode_base64, decode_base64, convert_base,
                                  Scratchpad, MAX_TEXT, MAX_NOTE)


class ConverterTests(unittest.TestCase):
    def test_json_korean_and_compact_roundtrip(self):
        raw = '{"이름":"도구","목록":[1,true,null]}'
        pretty = format_json(raw)
        self.assertIn('\n', pretty)
        self.assertIn('도구', pretty)
        self.assertEqual(format_json(pretty, compact=True), raw)
        self.assertEqual(format_json('false'), 'false')

    def test_json_errors_and_non_finite_values(self):
        for raw in ('{"a":}', 'NaN', 'Infinity', '-Infinity', '{"a":NaN}'):
            with self.assertRaises(ValueError):
                format_json(raw)
        with self.assertRaisesRegex(ValueError, '행'):
            format_json('{\n"a":}')

    def test_json_depth_and_size_limit(self):
        with self.assertRaises(ValueError):
            format_json('['*1500+'0'+']'*1500)
        with self.assertRaises(ValueError):
            format_json(' '* (MAX_TEXT+1))

    def test_json_preserves_numeric_precision_and_rejects_duplicate_keys(self):
        raw = '{"decimal":0.123456789012345678901234,"exponent":1e999,"integer":'+ '9'*5000+'}'
        self.assertEqual(format_json(raw,compact=True),raw)
        with self.assertRaisesRegex(ValueError, '중복 키'):
            format_json('{"a":1,"a":2}')
        self.assertEqual(format_json('"\\ud800"'), '"\\ud800"')

    def test_base64_utf8_and_whitespace_roundtrip(self):
        value = '서울 2호선 🚇\n안녕하세요!'
        encoded = encode_base64(value)
        self.assertEqual(decode_base64(encoded), value)
        self.assertEqual(decode_base64(' \n'+encoded[:8]+'\n'+encoded[8:]+'\t'), value)
        self.assertEqual(decode_base64(''), '')

    def test_base64_invalid_data(self):
        for raw in ('%bad%', 'YQ', '/w==', '가나다'):
            with self.assertRaises(ValueError):
                decode_base64(raw)
        with self.assertRaises(ValueError):
            encode_base64('a'*(MAX_TEXT+1))

    def test_all_base_pairs_and_signed_prefixes(self):
        values = {2:'11111111',8:'377',10:'255',16:'FF'}
        for source, raw in values.items():
            for target, expected in values.items():
                self.assertEqual(convert_base(raw,source,target),expected)
        self.assertEqual(convert_base('-0xFF',16,10),'-255')
        self.assertEqual(convert_base('+0b101',2,8),'5')
        self.assertEqual(convert_base('-0',10,2),'0')
        self.assertEqual(convert_base('0o77',8,16),'3F')

    def test_invalid_base_digits_and_limits(self):
        for raw, source in (('2',2),('8',8),('0x10',10),('1_000',10),('',10),('-',10)):
            with self.assertRaises(ValueError):
                convert_base(raw,source,16)
        with self.assertRaises(ValueError):
            convert_base('1',3,16)
        with self.assertRaises(ValueError):
            convert_base('1'*1025,10,2)
        self.assertEqual(len(convert_base('F'*1024,16,2)),4096)


class ScratchpadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'notes' / 'scratchpad.txt'
        self.note = Scratchpad(self.path)

    def test_unicode_restart_and_user_path_creation(self):
        text = '오프라인 메모\n서울 🚇'
        self.assertTrue(self.note.save(text))
        self.assertEqual(Scratchpad(self.path).text,text)
        self.assertFalse(self.path.with_suffix('.tmp').exists())

    def test_previous_save_and_restore_keep_current_copy(self):
        self.note.save('첫 번째')
        self.note.save('두 번째')
        self.assertEqual(self.note.backup.read_text(encoding='utf-8'),'첫 번째')
        self.assertEqual(self.note.restore_previous(),'첫 번째')
        self.assertEqual(self.path.read_text(encoding='utf-8'),'첫 번째')
        self.assertEqual(self.path.with_suffix('.before-restore.txt').read_text(encoding='utf-8'),'두 번째')

    def test_unchanged_save_does_not_rotate_previous_copy(self):
        self.note.save('one')
        self.note.save('two')
        self.note.save('two')
        self.assertEqual(self.note.backup.read_text(encoding='utf-8'),'one')

    def test_missing_backup_does_not_destroy_note(self):
        self.note.save('keep')
        self.assertIsNone(self.note.restore_previous())
        self.assertEqual(self.path.read_text(encoding='utf-8'),'keep')

    def test_failed_replace_keeps_saved_note_and_removes_temp(self):
        self.note.save('keep')
        with patch('mobile.offline_tools.os.replace',side_effect=OSError('disk')):
            self.assertFalse(self.note.save('new'))
        self.assertEqual(self.path.read_text(encoding='utf-8'),'keep')
        self.assertEqual(self.note.text,'keep')
        self.assertFalse(self.path.with_suffix('.tmp').exists())

    def test_corrupt_file_is_not_overwritten_and_backup_can_recover(self):
        self.note.save('previous')
        self.note.save('current')
        self.path.write_bytes(b'\xff\xff')
        damaged = Scratchpad(self.path)
        self.assertFalse(damaged.loaded)
        self.assertFalse(damaged.save('overwrite'))
        self.assertEqual(self.path.read_bytes(),b'\xff\xff')
        self.assertEqual(damaged.restore_previous(),'previous')
        self.assertTrue(damaged.save('recovered edit'))

    def test_max_note_and_overflow_preserve_saved_data(self):
        self.assertTrue(self.note.save('가'*MAX_NOTE))
        self.assertFalse(self.note.save('가'*(MAX_NOTE+1)))
        self.assertEqual(len(Scratchpad(self.path).text),MAX_NOTE)


if __name__ == '__main__':
    unittest.main()
