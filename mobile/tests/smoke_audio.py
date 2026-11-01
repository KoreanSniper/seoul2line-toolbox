"""실제 WAV 로딩·SDL 무음 출력·사운드보드 화면과 수명 주기 검사."""
import os
os.environ['SDL_AUDIODRIVER'] = 'dummy'
os.environ['KIVY_AUDIO'] = 'sdl2'
from pathlib import Path
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.popup import Popup
from mobile.tests.smoke_offline import OfflineSmokeApp
from mobile.tests.test_audio import make_wave
from mobile.audio_library import AudioLibrary


class AudioSmokeApp(OfflineSmokeApp):
    def on_start(self):
        Window.size = (420,860)
        self.source = make_wave(Path(self.temporary.name)/'검사용 무음.wav')
        self.steps = iter([self.import_audio,self.play_audio,self.stop_on_leave,self.remove_audio,self.check_removed])
        Clock.schedule_once(self.step,.3)

    def import_audio(self):
        self.go('soundboard')
        self.soundboard.import_file(self.source)
        assert self.audio_import.disabled

    def play_audio(self):
        assert not self.soundboard.busy
        assert len(self.soundboard.library.items) == 1
        self.item = self.soundboard.library.items[0]
        self.soundboard.play(self.item['id'])
        assert self.soundboard.backend.sound is not None
        assert self.soundboard.backend.sound.state == 'play'
        assert self.soundboard.backend.sound.length >= .09
        self.capture('soundboard-dark.png')

    def stop_on_leave(self):
        assert self.soundboard.active_id == '', '파일 종료 후 재생 상태가 유지됨'
        self.soundboard.play(self.item['id'])
        self.go('home')
        assert self.soundboard.backend.sound is None
        self.go('soundboard')
        self.theme('light')
        self.capture('soundboard-light.png')

    def remove_audio(self):
        self.confirm_audio_remove(self.item['id'])
        popup = next(w for w in Window.children if isinstance(w,Popup))
        next(w for w in popup.content.children if getattr(w,'text','') == '제거').dispatch('on_release')

    def check_removed(self):
        assert self.source.exists()
        assert self.soundboard.library.items == []
        assert AudioLibrary(self.soundboard.library.root).items == []
        self.on_pause()
        assert self.soundboard.backend.sound is None


if __name__ == '__main__':
    app = AudioSmokeApp()
    app.run()
    app.temporary.cleanup()
    if app.failed:
        raise app.failed
    print('MOBILE_AUDIO_SMOKE_OK: WAV import, real SDL dummy playback, completion, leave/pause stop, theme, remove, original preserved')
