"""임시 개인화 경로에서 실제 Kivy 실행·화면 이동·PNG 캡처.

저장소 루트에서 py -m mobile.tests.smoke_ui 실행.
"""
from pathlib import Path
import tempfile
from kivy.clock import Clock
from kivy.core.window import Window
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
                self.pin_menu('menu1')
                Clock.schedule_once(lambda _: self.stop(), .3)
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


if __name__ == '__main__':
    app = SmokeApp()
    app.run()
    app.temporary.cleanup()
    if app.failed:
        raise app.failed
    print('MOBILE_UI_SMOKE_OK: 3 themes, 5 tabs, search, navigation, persistence, popup')
