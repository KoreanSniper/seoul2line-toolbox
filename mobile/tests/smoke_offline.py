"""실제 Kivy 화면에서 오프라인 변환·메모·생명주기를 검증한다."""
from pathlib import Path
import tempfile
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.popup import Popup
from mobile.main import ToolboxApp
from mobile.offline_tools import Scratchpad


class OfflineSmokeApp(ToolboxApp):
    def __init__(self, **kwargs):
        self.temporary = tempfile.TemporaryDirectory()
        self.output = Path(__file__).resolve().parents[1] / 'local_data' / 'previews'
        self.output.mkdir(parents=True, exist_ok=True)
        self.failed = None
        super().__init__(**kwargs)

    def _get_user_data_dir(self):
        return self.temporary.name

    def on_start(self):
        Window.size = (420,860)
        self.steps = iter([self.json_conversion, self.base64_conversion, self.radix_conversion,
                           self.write_note, self.check_autosave, self.restore_note, self.check_restore])
        Clock.schedule_once(self.step, .3)

    def step(self, _):
        try:
            next(self.steps)()
            Clock.schedule_once(self.step, 1)
        except StopIteration:
            self.stop()
        except Exception as exc:
            self.failed = exc
            self.stop()

    def capture(self, name):
        Clock.schedule_once(lambda _: self.root.export_to_png(str(self.output / name)), .2)

    def json_conversion(self):
        self.go('converter')
        self.converter_input.text = '{"도구":"S2", "상태":true}'
        self.run_converter()
        assert '"도구": "S2"' in self.converter_output.text
        self.capture('offline-json-dark.png')

    def base64_conversion(self):
        self.update_conversion(operation='Base64 인코딩')
        self.render()
        self.converter_input.text = '서울 🚇'
        self.run_converter()
        result = self.converter_output.text
        self.update_conversion(operation='Base64 디코딩')
        self.render()
        self.converter_input.text = result
        self.run_converter()
        assert self.converter_output.text == '서울 🚇'
        self.converter_input.text = '%bad%'
        self.run_converter()
        assert self.converter_output.text == ''
        assert 'UTF-8' in self.converter_status.text

    def radix_conversion(self):
        self.update_conversion(operation='진법 변환',source='16',target='10')
        self.theme('green')
        self.converter_input.text = '-0xFF'
        self.run_converter()
        assert self.converter_output.text == '-255'
        self.capture('offline-radix-green.png')

    def write_note(self):
        self.go('scratchpad')
        self.note_input.text = '첫 번째 메모 🚇'
        # 이동 전에 입력한 글이 디바운스 타이머를 기다리지 않고 저장되어야 한다.
        self.go('home')
        assert Scratchpad(self.scratchpad.path).text == '첫 번째 메모 🚇'
        self.go('scratchpad')
        self.note_input.text = '두 번째 메모\n오프라인 자동 저장'

    def check_autosave(self):
        assert Scratchpad(self.scratchpad.path).text == '두 번째 메모\n오프라인 자동 저장'
        assert self.note_timer is None
        Window.size = (320,640)
        self.theme('light')
        assert self.note_input.text == '두 번째 메모\n오프라인 자동 저장'
        self.capture('offline-note-light-320.png')

    def restore_note(self):
        self.confirm_note_restore()
        popup = next(w for w in Window.children if isinstance(w, Popup))
        next(w for w in popup.content.children if getattr(w,'text','') == '이전 저장본으로 복구').dispatch('on_release')
        assert self.note_draft == '첫 번째 메모 🚇'

    def check_restore(self):
        assert self.note_input.text == '첫 번째 메모 🚇'
        self.note_input.text = '일시정지 전 마지막 입력'
        assert self.on_pause() is True
        assert Scratchpad(self.scratchpad.path).text == '일시정지 전 마지막 입력'
        assert self.note_timer is None


if __name__ == '__main__':
    app = OfflineSmokeApp()
    app.run()
    app.temporary.cleanup()
    if app.failed:
        raise app.failed
    print('MOBILE_OFFLINE_SMOKE_OK: JSON, Base64, radix, autosave, navigate, theme, restore, pause')
