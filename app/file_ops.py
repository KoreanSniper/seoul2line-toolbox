"""Retry short Windows file locks without hiding permanent access errors."""
import sys
import time


def retry_on_windows_lock(operation, *args):
    for attempt in range(5):
        try:
            return operation(*args)
        except PermissionError as error:
            if sys.platform != 'win32' or getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 4:
                raise
            time.sleep(.025 * (attempt + 1))
