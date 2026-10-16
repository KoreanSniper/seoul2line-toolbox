import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from app.file_ops import retry_on_windows_lock


def locked(code=32):
    error = PermissionError('file in use')
    error.winerror = code
    return error


class FileOperationTests(unittest.TestCase):
    def test_temporary_lock_retries_and_publishes_complete_file(self):
        root = Path(__file__).resolve().parents[1] / 'user_data'
        root.mkdir(exist_ok=True)
        with TemporaryDirectory(dir=root, prefix='file-retry-') as directory:
            source, target = Path(directory) / 'new.tmp', Path(directory) / 'saved.txt'
            source.write_text('new content')
            target.write_text('old content')
            attempts = []

            def replace(a, b):
                attempts.append(1)
                if len(attempts) < 3:
                    raise locked(5)
                os.replace(a, b)

            with patch('app.file_ops.sys.platform', 'win32'), patch('app.file_ops.time.sleep') as sleep:
                retry_on_windows_lock(replace, source, target)
            self.assertEqual(target.read_text(), 'new content')
            self.assertFalse(source.exists())
            self.assertEqual(sleep.call_count, 2)

    def test_persistent_lock_stops_and_preserves_existing_file(self):
        for code in (5, 32, 33):
            operation = Mock(side_effect=locked(code))
            with patch('app.file_ops.sys.platform', 'win32'), patch('app.file_ops.time.sleep') as sleep:
                with self.assertRaises(PermissionError):
                    retry_on_windows_lock(operation, 'source', 'target')
            self.assertEqual(operation.call_count, 5)
            self.assertEqual(sleep.call_count, 4)

    def test_other_errors_and_non_windows_are_not_retried(self):
        for platform, error in (('linux', locked()), ('win32', PermissionError('denied')),
                                ('win32', FileNotFoundError('missing'))):
            operation = Mock(side_effect=error)
            with patch('app.file_ops.sys.platform', platform), patch('app.file_ops.time.sleep') as sleep:
                with self.assertRaises(type(error)):
                    retry_on_windows_lock(operation)
            operation.assert_called_once()
            sleep.assert_not_called()
