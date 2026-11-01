"""임시 개인화 경로에서 실제 Kivy 실행·화면 이동·PNG 캡처.

저장소 루트에서 py -m mobile.tests.smoke_ui 실행.
"""
from pathlib import Path
import tempfile
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.tests.common import UnitTestTouch
from kivy.uix.popup import Popup
from mobile.main import ToolboxApp
from mobile.model import State


class SmokeApp(ToolboxApp):
    def __init__(self, **kwargs):
        self.temporary = tempfile.TemporaryDirectory()
        self.output = Path(__file__).resolve().parents[1] / 'local_data' / 'previews'
        self.output.mkdir(parents=True, exist_ok=True)
        self.failed = None
        super().__init__(**kwargs)

    def _get_user_data_dir(self):
        return self.temporary.name

    def on_start(self):
        self.steps = iter([
            ('dark', 'home', (420,860)), ('light','home',(420,860)),
            ('green','home',(420,860)), ('green','settings',(320,640)),
            ('dark','search',(320,640)), ('dark','pc',(420,860)),
        ])
        Clock.schedule_once(self.step, .3)

    def step(self, _):
        try:
            theme, page, size = next(self.steps)
            Window.size = size
            self.theme(theme)
            self.go(page)
            assert len(self.nav_buttons) == 5
            assert self.content.height > 0
            self.capture_name = f'{theme}-{page}-{size[0]}.png'
            if page == 'search':
                self.search_results('TTS')
                assert len(self.results.children) == 1
                self.search_results('존재하지않음')
                assert len(self.results.children) == 1
            Clock.schedule_once(self.capture, .3)
        except StopIteration:
            try:
                self.state.pin('menu2','notes')
                self.persist()
                assert State(self.state.path).pins['menu2'] == 'notes'
                self.go('tts')
                assert self.back(Window,27) is True
                assert self.page == 'home'
                Clock.schedule_once(self.short_tap, .2)
            except Exception as exc:
                self.failed = exc
                self.stop()
        except Exception as exc:
            self.failed = exc
            self.stop()

    def capture(self, _):
        try:
            self.root.export_to_png(str(self.output / self.capture_name))
            Clock.schedule_once(self.step, .1)
        except Exception as exc:
            self.failed = exc
            self.stop()

    def guarded(self, function):
        try:
            function()
        except Exception as exc:
            self.failed = exc
            self.stop()

    def short_tap(self, _):
        def run():
            self.short_target = self.state.tabs()['menu1']
            touch = UnitTestTouch(*self.nav_buttons['menu1'].center)
            touch.touch_down()
            touch.touch_up()
            Clock.schedule_once(self.begin_hold, .2)
        self.guarded(run)

    def begin_hold(self, _):
        def run():
            assert self.page == self.short_target, '짧은 탭으로 메뉴 이동 실패'
            self.before_hold = self.page
            self.touch = UnitTestTouch(*self.nav_buttons['menu2'].center)
            self.touch.touch_down()
            # 다른 손가락의 접촉/해제가 기존 길게 누르기를 취소하면 안 된다.
            other = UnitTestTouch(Window.width-30, Window.height-110)
            other.touch_down()
            other.touch_up()
            Clock.schedule_once(self.finish_hold, .7)
        self.guarded(run)

    def finish_hold(self, _):
        def run():
            self.touch.touch_up()
            assert self.page == self.before_hold, '길게 누르기 후 잘못된 메뉴 이동'
            popup = next(w for w in Window.children if isinstance(w, Popup))
            self.root.export_to_png(str(self.output / 'hold-underlying.png'))
            current = self.state.tabs()['menu2']
            button = next(w for w in popup.content.children if getattr(w,'text','') == '현재 탭 고정하기')
            button.dispatch('on_release')
            assert State(self.state.path).pins['menu2'] == current
            Clock.schedule_once(self.unpin_and_cancel, .3)
        self.guarded(run)

    def unpin_and_cancel(self, _):
        def run():
            self.pin_menu('menu2')
            popup = next(w for w in Window.children if isinstance(w, Popup))
            button = next(w for w in popup.content.children if getattr(w,'text','') == '고정 해제 · 자동 추천')
            button.dispatch('on_release')
            assert 'menu2' not in State(self.state.path).pins
            Clock.schedule_once(self.cancel_moved_hold, .3)
        self.guarded(run)

    def cancel_moved_hold(self, _):
        def run():
            self.touch = UnitTestTouch(*self.nav_buttons['menu1'].center)
            self.touch.touch_down()
            self.touch.touch_move(self.touch.x, self.touch.y+100)
            Clock.schedule_once(self.finish_cancel, .7)
        self.guarded(run)

    def finish_cancel(self, _):
        def run():
            self.touch.touch_up()
            assert not any(isinstance(w, Popup) for w in Window.children), '이동 후 길게 누르기 취소 실패'
            assert self.on_pause() is True
            self.touch = UnitTestTouch(*self.nav_buttons['menu1'].center)
            self.touch.touch_down()
            self.go('home')
            Clock.schedule_once(self.check_removed_button, .7)
        self.guarded(run)

    def check_removed_button(self, _):
        def run():
            self.touch.touch_up()
            assert self.page == 'home'
            assert not any(isinstance(w, Popup) for w in Window.children), '제거된 탭에서 고정창 열림'
            self.note_draft = '설정 초기화에서도 유지할 메모'
            self.flush_note()
            self.state.path.write_bytes(b'\xffbroken-settings')
            self.state = State(self.state.path)
            self.last_save_error = self.state.error
            self.go('settings')
            self.confirm_settings_reset()
            Clock.schedule_once(self.reset_settings, .3)
        self.guarded(run)

    def reset_settings(self, _):
        def run():
            popup = next(w for w in Window.children if isinstance(w, Popup))
            next(w for w in popup.content.children if getattr(w,'text','') == '백업 후 초기화').dispatch('on_release')
            assert State(self.state.path).readable
            backups = list(self.state.path.parent.glob('mobile-settings.before-reset-*.json'))
            assert len(backups) == 1
            assert backups[0].read_bytes() == b'\xffbroken-settings'
            assert self.scratchpad.path.read_text(encoding='utf-8') == '설정 초기화에서도 유지할 메모'
            self.stop()
        self.guarded(run)


if __name__ == '__main__':
    app = SmokeApp()
    app.run()
    app.temporary.cleanup()
    if app.failed:
        raise app.failed
    print('MOBILE_UI_SMOKE_OK: 3 themes, 5 tabs, search, restart, tap/hold, multi-touch, pin/unpin, move/detach cancellation, pause, backed-up settings reset')
