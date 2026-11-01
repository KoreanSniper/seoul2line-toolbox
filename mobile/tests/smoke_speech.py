"""네이티브 출력 대신 제어 대역을 사용한 실제 Kivy TTS 화면 검사."""
from kivy.clock import Clock
from kivy.core.window import Window
from mobile.tests.smoke_offline import OfflineSmokeApp
from mobile.tests.test_speech import FakeSpeech
from mobile.speech import SpeechController


class SpeechSmokeApp(OfflineSmokeApp):
    def on_start(self):
        Window.size = (420,860)
        self.steps = iter([self.unavailable, self.ready_speech, self.read_and_stop, self.leave_speech])
        Clock.schedule_once(self.step,.3)

    def unavailable(self):
        self.go('tts')
        assert self.speech_play.disabled
        assert 'Android' in self.speech_status.text

    def ready_speech(self):
        self.speech = SpeechController(FakeSpeech,self.speech_changed)
        self.speech.connect()
        self.speech.event('catalogue',dict(ready=True,engines=[dict(id='test',label='검사용 엔진')],
                                          voices=[dict(id='ko-offline',label='한국어 오프라인')],message='검사용 엔진 준비'))
        assert not self.speech_play.disabled
        self.speech_input.text = '안녕하세요. S2 Toolbox입니다.'
        self.theme('green')
        assert self.speech_input.text == '안녕하세요. S2 Toolbox입니다.'
        self.capture('speech-green.png')

    def read_and_stop(self):
        self.speech_play.dispatch('on_release')
        assert self.speech.backend.calls[-1][0] == 'speak'
        self.speech.stop()
        assert self.speech.backend.calls[-1] == ('stop',)
        assert '중지' in self.speech_status.text

    def leave_speech(self):
        self.speech.speak(self.speech_text)
        self.go('home')
        assert self.speech.backend.calls[-1] == ('stop',)
        self.on_pause()
        assert not self.speech.active_id


if __name__ == '__main__':
    app = SpeechSmokeApp()
    app.run()
    app.temporary.cleanup()
    if app.failed:
        raise app.failed
    print('MOBILE_SPEECH_UI_OK: unavailable, catalogue, text, theme, request, stop, leave, pause; native audio NOT tested')
