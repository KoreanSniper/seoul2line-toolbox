import unittest
from mobile.speech import SpeechController


class FakeSpeech:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []

    def initialize(self, engine):
        self.calls.append(('initialize',engine))

    def speak(self, *args):
        self.calls.append(('speak',*args))

    def stop(self):
        self.calls.append(('stop',))

    def close(self):
        self.calls.append(('close',))


class SpeechTests(unittest.TestCase):
    def ready(self):
        speech = SpeechController(FakeSpeech)
        speech.connect()
        speech.event('catalogue',dict(ready=True,engines=[dict(id='engine',label='엔진')],
                                      voices=[dict(id='ko-offline',label='한국어')],message='준비 완료'))
        return speech

    def test_desktop_is_unavailable_without_native_import(self):
        speech = SpeechController()
        speech.connect()
        speech.speak('안녕하세요')
        self.assertFalse(speech.ready)
        self.assertIsNone(speech.backend)

    def test_connect_catalogue_and_speak_request(self):
        speech = self.ready()
        speech.speak('안녕하세요',1.25)
        call = speech.backend.calls[-1]
        self.assertEqual(call[:4],('speak','안녕하세요','ko-offline',1.25))
        self.assertEqual(call[4],speech.active_id)

    def test_utf16_limit_and_blank_input(self):
        speech = self.ready()
        for text in (' ', '가'*4001, '🚇'*2001):
            speech.speak(text)
            self.assertFalse(any(call[0]=='speak' for call in speech.backend.calls))
        speech.speak('🚇'*2000)
        self.assertEqual(speech.backend.calls[-1][0],'speak')

    def test_rate_validation_and_missing_voice(self):
        speech = self.ready()
        for rate in (0,3,float('nan'),'bad'):
            speech.speak('안녕',rate)
        self.assertFalse(any(call[0]=='speak' for call in speech.backend.calls))
        speech.voice = 'missing'
        speech.speak('안녕')
        self.assertIn('선택',speech.status)

    def test_previous_request_completion_is_ignored(self):
        speech = self.ready()
        speech.speak('첫 번째')
        old = speech.active_id
        speech.speak('두 번째')
        current = speech.active_id
        speech.event('done',dict(id=old,message='오래된 완료'))
        self.assertEqual(speech.active_id,current)
        speech.event('done',dict(id=current,message='완료'))
        self.assertEqual(speech.active_id,'')
        self.assertEqual(speech.status,'완료')

    def test_stop_and_close_ignore_late_events(self):
        speech = self.ready()
        speech.speak('안녕')
        request = speech.active_id
        speech.stop()
        speech.event('started',dict(id=request,message='뒤늦은 시작'))
        self.assertEqual(speech.status,'읽기를 중지했습니다.')
        backend = speech.backend
        speech.close()
        speech.event('catalogue',dict(ready=True,voices=[dict(id='bad')]))
        self.assertFalse(speech.ready)
        self.assertEqual(backend.calls[-1],('close',))

    def test_engine_switch_clears_old_voice_and_request(self):
        speech = self.ready()
        speech.speak('안녕')
        speech.connect('other-engine')
        self.assertFalse(speech.ready)
        self.assertEqual(speech.voice,'')
        self.assertEqual(speech.active_id,'')
        self.assertEqual(speech.backend.calls[-1],('initialize','other-engine'))

    def test_no_offline_voice_and_native_error(self):
        speech = self.ready()
        speech.event('catalogue',dict(ready=True,engines=[],voices=[],message='음성 없음'))
        self.assertFalse(speech.ready)
        speech.event('error',dict(id='',message='초기화 실패'))
        self.assertEqual(speech.status,'초기화 실패')

    def test_backend_failure_can_retry(self):
        calls = []
        def factory(callback):
            if not calls:
                calls.append('failed')
                raise RuntimeError('missing')
            return FakeSpeech(callback)
        speech = SpeechController(factory)
        speech.connect()
        self.assertIsNone(speech.backend)
        speech.connect()
        self.assertIsInstance(speech.backend,FakeSpeech)


if __name__ == '__main__':
    unittest.main()
