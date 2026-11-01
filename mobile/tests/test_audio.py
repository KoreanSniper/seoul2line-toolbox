import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import wave
from mobile.audio_library import AudioLibrary
from mobile.audio import SoundboardController


def make_wave(path):
    with wave.open(str(path),'wb') as out:
        out.setparams((1,2,8000,0,'NONE','not compressed'))
        out.writeframes(b'\x00\x00'*800)
    return path


class FakeAudio:
    def __init__(self, callback):
        self.callback, self.calls = callback, []

    def play(self, path, request):
        self.calls.append(('play',path,request))

    def stop(self):
        self.calls.append(('stop',))

    def choose(self, destination):
        self.calls.append(('choose',str(destination)))

    def close(self):
        self.calls.append(('close',))


class AudioTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = make_wave(self.root/'알림 소리.wav')
        self.library = AudioLibrary(self.root/'audio')

    def test_import_restart_and_original_preserved(self):
        original = self.source.read_bytes()
        item = self.library.import_file(self.source)
        restored = AudioLibrary(self.library.root)
        self.assertEqual(restored.items,[item])
        self.assertEqual(restored.path_for(item['id']).read_bytes(),original)
        self.assertEqual(self.source.read_bytes(),original)

    def test_invalid_extension_empty_and_size_limit_leave_no_files(self):
        for name, data in (('bad.txt',b'123'),('empty.wav',b''),('large.wav',b'a'*65)):
            source = self.root/name
            source.write_bytes(data)
            with patch('mobile.audio_library.MAX_AUDIO_BYTES',64):
                with self.assertRaises(ValueError):
                    self.library.import_file(source)
        self.assertFalse(self.library.items)
        self.assertFalse(list(self.library.root.glob('.incoming-*')))

    def test_import_transaction_failure_keeps_source_and_original_index(self):
        first = self.library.import_file(self.source)
        before = self.library.index.read_bytes()
        with patch.object(self.library,'_persist',side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.library.import_file(self.source)
        self.assertEqual(self.library.items,[first])
        self.assertEqual(self.library.index.read_bytes(),before)
        self.assertEqual(len(list(self.library.root.glob('*.wav'))),1)
        self.assertTrue(self.source.exists())

    def test_remove_rollback_and_success(self):
        item = self.library.import_file(self.source)
        file = self.library.path_for(item['id'])
        with patch.object(self.library,'_persist',side_effect=OSError('disk')):
            with self.assertRaises(OSError):
                self.library.remove(item['id'])
        self.assertTrue(file.exists())
        self.assertEqual(AudioLibrary(self.library.root).items,[item])
        self.library.remove(item['id'])
        self.assertFalse(file.exists())
        self.assertEqual(AudioLibrary(self.library.root).items,[])
        self.assertTrue(self.source.exists())

    def test_untrusted_index_path_is_rejected_without_overwrite(self):
        self.library.root.mkdir()
        self.library.index.write_text(json.dumps(dict(version=1,items=[dict(id='../outside',extension='.wav',name='bad',bytes=1)])),encoding='utf-8')
        broken = AudioLibrary(self.library.root)
        before = broken.index.read_bytes()
        self.assertFalse(broken.readable)
        with self.assertRaises(ValueError):
            broken.import_file(self.source)
        self.assertEqual(broken.index.read_bytes(),before)

    def test_staging_requires_owned_path_and_mime_fallback(self):
        with self.assertRaises(ValueError):
            self.library.commit_staging(self.source,'test.wav')
        staging = self.library.staging_path()
        staging.write_bytes(self.source.read_bytes())
        item = self.library.commit_staging(staging,'확장자 없는 사운드','audio/wav')
        self.assertEqual(item['extension'],'.wav')

    def test_limit_and_cancelled_import(self):
        with patch('mobile.audio_library.MAX_ITEMS',1):
            self.library.import_file(self.source)
            with self.assertRaises(ValueError):
                self.library.import_file(self.source)
        other = AudioLibrary(self.root/'other')
        with self.assertRaises(ValueError):
            other.import_file(self.source,lambda: True)
        self.assertFalse(other.items)
        self.assertFalse(list(other.root.glob('.incoming-*')))

    def controller(self):
        return SoundboardController(self.root/'controller',FakeAudio)

    def test_async_import_busy_and_playback_events(self):
        controller = self.controller()
        controller.import_file(self.source)
        controller.worker.join(3)
        self.assertFalse(controller.busy)
        key = controller.library.items[0]['id']
        controller.play(key)
        old = controller.active_id
        controller.play(key)
        current = controller.active_id
        controller.event('done',dict(id=old,message='old'))
        self.assertEqual(controller.active_id,current)
        controller.event('done',dict(id=current,message='완료'))
        self.assertEqual(controller.active_id,'')

    def test_android_selection_cancel_and_copied_file_commit(self):
        controller = self.controller()
        controller.choose_android()
        self.assertTrue(controller.busy)
        controller.event('import_cancelled',{})
        self.assertFalse(controller.busy)
        controller.choose_android()
        pending = controller.pending
        pending.write_bytes(self.source.read_bytes())
        controller.event('imported',dict(path=str(pending),name='선택한 소리.wav',mime='audio/wav'))
        self.assertFalse(controller.busy)
        self.assertEqual(len(controller.library.items),1)
        self.assertFalse(pending.exists())

    def test_invalid_callback_path_and_close_cleanup(self):
        controller = self.controller()
        controller.choose_android()
        pending = controller.pending
        pending.write_bytes(b'partial')
        controller.event('imported',dict(path='/outside',name='bad.wav'))
        self.assertEqual(controller.library.items,[])
        self.assertFalse(pending.exists())
        controller.choose_android()
        pending = controller.pending
        pending.write_bytes(b'partial')
        controller.close()
        self.assertFalse(pending.exists())
        controller.event('done',dict(id='',message='late'))
        self.assertTrue(controller.closed)


if __name__ == '__main__':
    unittest.main()
