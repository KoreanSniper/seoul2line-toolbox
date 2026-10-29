"""Local rotating diagnostic log; never records TTS text or preset contents."""
import logging
from logging.handlers import RotatingFileHandler
import sys
import threading

from app.paths import data_directory


_lock = threading.Lock()


def log_failure():
    with _lock:
        handler = None
        try:
            folder = data_directory() / "logs"
            folder.mkdir(parents=True, exist_ok=True)
            handler = RotatingFileHandler(folder / "voice_fx.log", maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            record = logging.getLogger("toolbox.voice_fx").makeRecord(
                "toolbox.voice_fx", logging.ERROR, __file__, 0, "음성 작업 실패", (), sys.exc_info())
            handler.handle(record)
        except OSError:
            pass
        finally:
            if handler is not None:
                handler.close()
