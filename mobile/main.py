"""실행: py mobile/main.py 또는 mobile/에서 python main.py."""
import os
from pathlib import Path

os.environ.setdefault('KIVY_NO_ARGS', '1')
from kivy.config import Config
from kivy.utils import platform, get_color_from_hex as rgba

if platform not in ('android', 'ios'):
    Config.set('graphics', 'width', '420')
    Config.set('graphics', 'height', '860')
    Config.set('graphics', 'minimum_width', '320')
    Config.set('graphics', 'minimum_height', '480')

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle, Line, Mesh, Ellipse
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.spinner import Spinner
try:
    from .model import State, THEMES, MENUS, TOOLS
    from .offline_tools import (Scratchpad, format_json, encode_base64, decode_base64,
                                convert_base, MAX_NOTE)
except ImportError:
    from model import State, THEMES, MENUS, TOOLS
    from offline_tools import (Scratchpad, format_json, encode_base64, decode_base64,
                               convert_base, MAX_NOTE)

ASSETS = Path(__file__).resolve().parent / 'assets'
LabelBase.register(name='S2Korean', fn_regular=str(ASSETS / 'NanumGothic-Regular.ttf'))


class Surface(BoxLayout):
    def __init__(self, color, border=None, radius=18, **kwargs):
        super().__init__(**kwargs)
        self.fill, self.edge, self.radius = color, border, dp(radius)
        self.bind(pos=self.paint, size=self.paint)

    def paint(self, *_):
        self.canvas.before.clear()
        with self.canvas.before:
            Color(*rgba(self.fill))
            RoundedRectangle(pos=self.pos, size=self.size, radius=[self.radius])
            if self.edge:
                Color(*rgba(self.edge))
                Line(rounded_rectangle=(*self.pos, *self.size, self.radius), width=dp(.8))


class Backdrop(Surface):
    def paint(self, *_):
        super().paint()
        app = App.get_running_app()
        p = app.colors
        x, y, w, h = *self.pos, *self.size
        with self.canvas.before:
            Color(*rgba(p['secondary'])[:3], .06)
            for shift in (0, .15, .30):
                points = [(x+w*(.12+shift), y), (x+w*(.36+shift), y),
                          (x+w, y+h*(.35+shift)), (x+w, y+h*(.49+shift))]
                Mesh(vertices=[v for px, py in points for v in (px, py, 0, 0)],
                     indices=[0, 1, 2, 3], mode='triangle_fan')
            Color(*rgba(p['secondary'])[:3], .35)
            Line(points=[x, y+h*.92, x+dp(22), y+h*.92-dp(22), x+dp(22), y+h*.65], width=dp(.7))
            for row in range(3):
                for col in range(4):
                    Ellipse(pos=(x+w-dp(48)+col*dp(9), y+h-dp(24)-row*dp(9)), size=(dp(2), dp(2)))


class LogoButton(ButtonBehavior, Image):
    pass


class NavButton(Button):
    """글꼴에 의존하지 않는 선 아이콘과 길게 누르기."""
    def __init__(self, icon, held=None, **kwargs):
        super().__init__(font_name='S2Korean', font_size=dp(11), background_normal='',
                         background_down='', background_color=(0, 0, 0, 0),
                         shorten=True, shorten_from='right', max_lines=1, **kwargs)
        self.icon, self.held, self.timer, self.did_hold = icon, held, None, False
        self.hold_touch = None
        self.gesture_cancelled = False
        self.valign = 'bottom'
        self.halign = 'center'
        self.padding = (0, dp(6))
        self.bind(pos=self.draw, size=self.draw, color=self.draw)
        self.bind(parent=self.parent_changed)

    def draw(self, *_):
        self.text_size = self.size
        self.canvas.after.clear()
        x, y, r = self.center_x, self.y + self.height * .65, dp(10)
        def line(points, close=False):
            Line(points=[n for a, b in points for n in (x+a*r, y+b*r)], close=close, width=dp(1.3))
        with self.canvas.after:
            Color(*self.color)
            if self.icon == 'home':
                line([(-1,-.1),(0,1),(1,-.1)])
                line([(-.7,.1),(-.7,-1),(-.2,-1),(-.2,-.3),(.2,-.3),(.2,-1),(.7,-1),(.7,.1)])
            elif self.icon == 'search':
                Line(circle=(x-dp(2),y+dp(2),dp(8)), width=dp(1.3))
                line([(.4,-.4),(1,-1)])
            elif self.icon == 'grid':
                for a in (-1, .2):
                    for b in (-1, .2):
                        Line(rectangle=(x+a*r,y+b*r,r*.8,r*.8),width=dp(1.2))
            elif self.icon == 'folder':
                line([(-1,-.8),(-1,.8),(-.2,.8),(.1,.4),(1,.4),(1,-.8)], True)
            elif self.icon == 'star':
                import math
                line([(math.sin(i*math.pi/5)*(1 if i%2==0 else .45),
                       math.cos(i*math.pi/5)*(1 if i%2==0 else .45)) for i in range(10)], True)
            else:
                Line(circle=(x,y,r*.7),width=dp(1.3))
                Line(circle=(x,y,r*.25),width=dp(1.3))
                for a,b in ((1,0),(-1,0),(0,1),(0,-1)):
                    line([(a*.7,b*.7),(a*1.1,b*1.1)])

    def on_touch_down(self, touch):
        accepted = super().on_touch_down(touch)
        if accepted and self.collide_point(*touch.pos) and self.held and self.hold_touch is None:
            self.hold_touch = touch
            self.did_hold = False
            self.gesture_cancelled = False
            self.timer = Clock.schedule_once(self.long_press, .55)
            self.start_touch = touch.pos
        return accepted

    def on_touch_move(self, touch):
        if touch is self.hold_touch and (abs(touch.x-self.start_touch[0]) + abs(touch.y-self.start_touch[1]) > dp(15)):
            self.cancel_timer()
            self.gesture_cancelled = True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch is self.hold_touch and touch.grab_current is self:
            self.cancel_timer()
            self.hold_touch = None
            suppressed = self.did_hold or self.gesture_cancelled or self.get_root_window() is None
            self.did_hold = False
            if suppressed:
                touch.ungrab(self)
                self.state = 'normal'
                return True
        return super().on_touch_up(touch)

    def long_press(self, _):
        self.timer = None
        if self.get_root_window() is None or self.gesture_cancelled:
            self.gesture_cancelled = True
            return
        self.did_hold = True
        self.held()

    def cancel_timer(self):
        if self.timer:
            self.timer.cancel()
            self.timer = None

    def parent_changed(self, _, parent):
        if parent is None:
            self.cancel_timer()
            self.gesture_cancelled = True


class ToolboxApp(App):
    title = 'S2 Toolbox'
    icon = str(ASSETS / 'toolbox-logo.png')

    @property
    def colors(self):
        return THEMES[self.state.theme]

    def build(self):
        self.state = State(Path(self.user_data_dir) / 'mobile-settings.json')
        self.scratchpad = Scratchpad(Path(self.user_data_dir) / 'scratchpad.txt')
        self.note_draft = self.scratchpad.text
        self.note_timer = None
        self.note_status = None
        self.last_save_error = ''
        self.converter = dict(operation='JSON 정리', text='', result='', status='', source='10', target='16')
        self.page = 'home'
        self.root_box = BoxLayout(orientation='vertical')
        self.root_box.bind(size=self.fit_note)
        Window.softinput_mode = 'below_target'
        Window.bind(on_keyboard=self.back)
        self.render()
        return self.root_box

    def label(self, text, size=14, muted=False, height=28):
        label = Label(text=text, font_name='S2Korean', font_size=dp(size),
                      color=rgba(self.colors['muted' if muted else 'text']),
                      halign='left', valign='middle', size_hint_y=None, height=dp(height))
        label.bind(size=lambda obj, value: setattr(obj, 'text_size', value))
        return label

    def button(self, text, action, primary=False, height=52):
        button = Button(text=text, font_name='S2Korean', font_size=dp(14), size_hint_y=None,
                        height=dp(height), background_normal='', background_down='',
                        background_color=rgba(self.colors['active' if primary else 'panel']),
                        color=rgba(self.colors['ink' if primary else 'text']))
        button.bind(on_release=lambda *_: action())
        return button

    def persist(self):
        if not self.state.save():
            if self.last_save_error != self.state.error:
                self.notice('저장 오류', self.state.error)
                self.last_save_error = self.state.error
        else:
            self.last_save_error = ''

    def go(self, key):
        self.flush_note()
        self.state.visit(key)
        self.page = key
        self.persist()
        self.render()

    def render(self):
        p = self.colors
        Window.clearcolor = rgba(p['bg'])
        self.root_box.clear_widgets()
        self.note_status = None
        header = Surface(p['panel'], p['border'], orientation='horizontal', size_hint_y=None,
                         height=dp(88), padding=[dp(16),dp(12)], spacing=dp(10))
        logo = LogoButton(source=str(ASSETS / 'toolbox-logo.png'), size_hint_x=None, width=dp(58))
        logo.bind(on_release=lambda *_: self.go('home'))
        header.add_widget(logo)
        brand = self.button('S2 Toolbox', lambda: self.go('home'), height=60)
        brand.font_size = dp(22)
        brand.size_hint_y = 1
        brand.size_hint_x = None
        brand.width = dp(150)
        brand.background_color = (0,0,0,0)
        brand.color = rgba(p['accent'])
        header.add_widget(brand)
        header.add_widget(BoxLayout())
        search = NavButton('search', text='', size_hint_x=None, width=dp(48), color=rgba(p['accent']))
        search.bind(on_release=lambda *_: self.go('search'))
        header.add_widget(search)
        self.root_box.add_widget(header)
        backdrop = Backdrop(p['bg'], orientation='vertical', padding=[dp(20),dp(14)])
        scroll = ScrollView(do_scroll_x=False)
        self.content = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(12))
        self.content.bind(minimum_height=self.content.setter('height'))
        scroll.add_widget(self.content)
        backdrop.add_widget(scroll)
        self.root_box.add_widget(backdrop)
        self.build_page()
        nav = Surface(p['panel'], p['border'], orientation='horizontal', size_hint_y=None,
                      height=dp(80), padding=[dp(6),dp(5),dp(6),dp(10)], spacing=dp(3))
        tabs = self.state.tabs()
        self.nav_buttons = {}
        for slot, icon, key in [('menu1','folder',tabs['menu1']), ('menu2','grid',tabs['menu2']),
                                 ('home','home','home'), ('tool1','star',tabs['tool1']), ('settings','settings','settings')]:
            name = MENUS.get(key, TOOLS.get(key, (key,))[0])
            name = {'home':'홈','settings':'설정'}.get(key,name)
            pinned = slot in self.state.pins
            button = NavButton(icon, text=name + (' · 고정' if pinned else ''),
                               color=rgba(p['accent'] if key == self.page else p['text']),
                               held=(lambda s=slot: self.pin_menu(s)) if slot in tabs else None)
            button.bind(on_release=lambda _, k=key: self.go(k))
            if key == self.page:
                button.background_color = rgba(p['active'])
                button.color = rgba(p['ink'])
            nav.add_widget(button)
            self.nav_buttons[slot] = button
        self.root_box.add_widget(nav)

    def build_page(self):
        add = self.content.add_widget
        if self.page == 'home':
            add(self.label('MY POCKET WORKSPACE', 11, True))
            add(self.label('나의 도구, 어디서나.', 26, height=44))
            add(self.label('익숙한 Toolbox를 이제 손안에서.', 13, True))
            card = Surface(self.colors['panel'], self.colors['border'], orientation='vertical',
                           size_hint_y=None, height=dp(118), padding=dp(16), spacing=dp(5))
            card.add_widget(self.label('PC 연결 대기', 17))
            card.add_widget(self.label('변환기와 메모는 오프라인으로 사용할 수 있어요.', 12, True))
            card.add_widget(self.label('Cloudflare 연동은 준비 중입니다.', 12, True))
            add(card)
            add(self.label('빠르게 둘러보기', 18, height=34))
            for key in ('converter','scratchpad','tts','soundboard'):
                self.tool_card(key)
            add(self.label('추천 탭을 길게 눌러 고정할 수 있어요.', 12, True, 36))
        elif self.page == 'converter':
            self.build_converter()
        elif self.page == 'scratchpad':
            self.build_scratchpad()
        elif self.page == 'settings':
            add(self.label('설정', 26, height=46))
            add(self.label('내 Toolbox의 분위기', 15))
            for key, name in [('dark','다크'),('light','라이트'),('green','그린')]:
                add(self.button(('●  ' if self.state.theme == key else '○  ') + name,
                                lambda k=key: self.theme(k), self.state.theme == key))
            add(self.label('하단 탭 개인화', 18, height=44))
            add(self.label('사용 빈도에 따라 메뉴 2개와 도구 1개를 추천합니다.', 12, True))
            for slot, name in [('menu1','메뉴 1'),('menu2','메뉴 2'),('tool1','도구 1')]:
                add(self.button(name+' 고정 설정', lambda s=slot: self.pin_menu(s)))
            add(self.label('S2 Toolbox Mobile · 0.1.0', 12, True, 48))
            if self.state.error:
                add(self.label(self.state.error, 12, True, 60))
                if not self.state.readable:
                    add(self.button('기존 설정 백업 후 초기화', self.confirm_settings_reset))
        elif self.page == 'search':
            add(self.label('도구 검색', 26, height=46))
            field = TextInput(hint_text='이름 또는 기능으로 검색', multiline=False, font_name='S2Korean',
                              size_hint_y=None, height=dp(50), font_size=dp(15),
                              background_color=rgba(self.colors['panel']), foreground_color=rgba(self.colors['text']),
                              hint_text_color=rgba(self.colors['muted']), padding=[dp(12),dp(14)])
            add(field)
            self.results = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(10))
            self.results.bind(minimum_height=self.results.setter('height'))
            add(self.results)
            field.bind(text=lambda _, text: self.search_results(text))
            self.search_results('')
        elif self.page in MENUS:
            add(self.label(MENUS[self.page], 26, height=46))
            for key, (_, menu, _) in TOOLS.items():
                if menu == self.page:
                    self.tool_card(key)
        else:
            name, menu, description = TOOLS[self.page]
            add(self.label(MENUS[menu], 12, True))
            add(self.label(name, 26, height=46))
            add(self.label(description, 14, True, 42))
            add(self.label('이 도구는 다음 개발 단계에서 제공됩니다.', 14, height=56))
            if menu == 'pc':
                add(self.label('기기 인증과 Cloudflare 연결 후 사용할 수 있어요.', 12, True, 46))
            add(self.button('홈으로', lambda: self.go('home'), True))

    def tool_card(self, key, target=None):
        name, _, description = TOOLS[key]
        (target if target is not None else self.content).add_widget(
            self.button(f'{name}   ›\n{description}', lambda: self.go(key), height=70))

    def search_results(self, query):
        self.results.clear_widgets()
        keys = self.state.search(query)
        for key in keys:
            self.tool_card(key, self.results)
        if not keys:
            self.results.add_widget(self.label('검색 결과가 없습니다.', 14, True, 60))

    def theme(self, key):
        self.flush_note()
        self.state.theme = key
        self.persist()
        self.render()

    def pin_menu(self, slot):
        box = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(8))
        popup = Popup(title='하단 탭 고정', title_font='S2Korean', content=box,
                      size_hint=(.92,.8), auto_dismiss=True)
        def select(key):
            if key is None:
                self.state.pins.pop(slot, None)
            else:
                self.state.pin(slot, key)
            self.persist()
            popup.dismiss()
            self.render()
        current = self.state.tabs()[slot]
        box.add_widget(self.button('현재 탭 고정하기', lambda: select(current), True))
        box.add_widget(self.button('고정 해제 · 자동 추천', lambda: select(None)))
        scroll = ScrollView()
        choices = BoxLayout(orientation='vertical', size_hint_y=None, spacing=dp(6))
        choices.bind(minimum_height=choices.setter('height'))
        for key, value in (TOOLS if slot == 'tool1' else MENUS).items():
            choices.add_widget(self.button(value[0] if slot == 'tool1' else value, lambda k=key: select(k)))
        scroll.add_widget(choices)
        box.add_widget(scroll)
        box.add_widget(self.button('닫기', popup.dismiss))
        popup.open()

    def notice(self, title, text):
        Popup(title=title, title_font='S2Korean', content=self.label(text, 13, height=90),
              size_hint=(.9,None), height=dp(180)).open()

    def back(self, _, key, *_args):
        if key == 27 and self.page != 'home':
            self.go('home')
            return True
        return False

    def on_pause(self):
        self.flush_note()
        self.persist()
        return True

    def on_stop(self):
        self.flush_note()
        self.persist()

    def input_field(self, text='', height=180, readonly=False):
        return TextInput(text=text, font_name='S2Korean', font_size=dp(14), multiline=True,
                         readonly=readonly, size_hint_y=None, height=dp(height), padding=dp(12),
                         background_normal='', background_active='',
                         background_color=rgba(self.colors['panel']),
                         foreground_color=rgba(self.colors['text']), cursor_color=rgba(self.colors['accent']))

    def spinner(self, text, values, callback):
        widget = Spinner(text=text, values=values, font_name='S2Korean', font_size=dp(14),
                         size_hint_y=None, height=dp(48), background_normal='',
                         background_color=rgba(self.colors['panel']), color=rgba(self.colors['text']))
        # 드롭다운 항목도 한국어 글꼴을 사용한다.
        from kivy.uix.spinner import SpinnerOption
        class KoreanOption(SpinnerOption):
            def __init__(self, **kwargs):
                super().__init__(font_name='S2Korean', font_size=dp(14), height=dp(48), **kwargs)
        widget.option_cls = KoreanOption
        widget.bind(text=lambda _, value: callback(value))
        return widget

    def build_converter(self):
        add = self.content.add_widget
        add(self.label('개발자 변환기', 26, height=46))
        add(self.label('네트워크 없이 변환 · 입력 32,768자 이내', 12, True))
        operations = ('JSON 정리', 'JSON 압축', 'Base64 인코딩', 'Base64 디코딩', '진법 변환')
        def operation(value):
            self.update_conversion(operation=value)
            self.render()
        add(self.spinner(self.converter['operation'], operations, operation))
        if self.converter['operation'] == '진법 변환':
            add(self.label('입력 진법  →  출력 진법', 13, True))
            row = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(10))
            for key in ('source','target'):
                row.add_widget(self.spinner(self.converter[key], ('2','8','10','16'),
                                             lambda value, k=key: self.update_conversion(**{k:value})))
            add(row)
        self.converter_input = self.input_field(self.converter['text'], 170)
        self.converter_input.hint_text = '변환할 내용을 입력하세요'
        self.converter_input.hint_text_color = rgba(self.colors['muted'])
        self.converter_input.bind(text=lambda _, value: self.update_conversion(text=value))
        add(self.converter_input)
        add(self.button('변환하기', self.run_converter, True))
        self.converter_status = self.label(self.converter['status'], 12, True, 50)
        add(self.converter_status)
        self.converter_output = self.input_field(self.converter['result'], 170, readonly=True)
        add(self.converter_output)
        add(self.button('결과 복사', self.copy_conversion))

    def update_conversion(self, **changes):
        self.converter.update(changes)
        self.converter.update(result='', status='입력이 변경되었습니다. 변환하기를 눌러 주세요.')
        if self.page == 'converter' and hasattr(self, 'converter_output'):
            self.converter_output.text = ''
            self.converter_status.text = self.converter['status']

    def run_converter(self):
        c = self.converter
        try:
            op, text = c['operation'], c['text']
            if op.startswith('JSON'):
                result = format_json(text, compact=op == 'JSON 압축')
            elif op == 'Base64 인코딩':
                result = encode_base64(text)
            elif op == 'Base64 디코딩':
                result = decode_base64(text)
            else:
                result = convert_base(text, int(c['source']), int(c['target']))
            c.update(result=result, status=f'변환 완료 · {len(result):,}자')
        except ValueError as exc:
            c.update(result='', status=str(exc))
        self.converter_output.text = c['result']
        self.converter_status.text = c['status']

    def copy_conversion(self):
        if not self.converter['result']:
            self.converter_status.text = '먼저 변환 결과를 만들어 주세요.'
            return
        try:
            Clipboard.copy(self.converter['result'])
            self.converter_status.text = '결과를 복사했습니다.'
        except Exception:
            self.converter_status.text = '복사하지 못했습니다. 결과를 길게 눌러 선택해 주세요.'

    def build_scratchpad(self):
        add = self.content.add_widget
        add(self.label('스크래치패드', 26, height=46))
        add(self.label('기기에만 저장 · 입력 후 자동 저장', 12, True))
        self.note_input = self.input_field(self.note_draft, 310)
        self.fit_note()
        self.note_input.bind(text=self.note_changed)
        add(self.note_input)
        self.note_status = self.label('', 12, True, 52)
        self.update_note_status()
        add(self.note_status)
        add(self.button('지금 저장', self.flush_note, True))
        add(self.button('이전 저장본 복구', self.confirm_note_restore))
        add(self.label('이전 저장본은 한 단계 보관합니다.', 12, True, 40))

    def fit_note(self, *_):
        if self.page == 'scratchpad' and hasattr(self, 'note_input'):
            self.note_input.height = min(dp(310), max(dp(140), self.root_box.height-dp(480)))

    def note_changed(self, _, text):
        self.note_draft = text
        if self.note_timer:
            self.note_timer.cancel()
        self.note_timer = Clock.schedule_once(lambda _: self.flush_note(), .7)
        self.update_note_status(pending=True)

    def update_note_status(self, pending=False):
        if self.note_status is not None:
            status = self.scratchpad.error or ('저장 대기 중' if pending else '기기에 저장됨')
            if not self.scratchpad.path.exists() and not pending and not self.scratchpad.error:
                status = '메모를 입력해 주세요'
            self.note_status.text = f'{len(self.note_draft):,} / {MAX_NOTE:,}자 · {status}'

    def flush_note(self):
        if self.note_timer:
            self.note_timer.cancel()
            self.note_timer = None
        if self.note_draft != self.scratchpad.text:
            self.scratchpad.save(self.note_draft)
        elif self.scratchpad.loaded:
            self.scratchpad.error = ''
        self.update_note_status()

    def confirm_note_restore(self):
        self.flush_note()
        if self.note_draft != self.scratchpad.text:
            self.notice('복구 안내', '현재 메모를 저장하지 못해 복구를 중단했습니다.')
            return
        box = BoxLayout(orientation='vertical', spacing=dp(10), padding=dp(12))
        box.add_widget(self.label('이전 저장본으로 바꿀까요?\n현재 저장본도 별도로 보관합니다.', 13, height=72))
        popup = Popup(title='메모 복구', title_font='S2Korean', content=box,
                      size_hint=(.92,None), height=dp(260))
        def restore():
            text = self.scratchpad.restore_previous()
            if text is not None:
                self.note_draft = text
            popup.dismiss()
            self.render()
        box.add_widget(self.button('이전 저장본으로 복구', restore, True))
        box.add_widget(self.button('취소', popup.dismiss))
        popup.open()

    def confirm_settings_reset(self):
        box = BoxLayout(orientation='vertical', spacing=dp(8), padding=dp(12))
        box.add_widget(self.label('기존 설정 파일을 별도 보관한 뒤\n테마·사용 횟수·고정을 초기화합니다.\n메모는 유지됩니다.', 13, height=84))
        popup = Popup(title='설정 복구', title_font='S2Korean', content=box,
                      size_hint=(.92,None), height=dp(270))
        def reset():
            if self.state.reset():
                self.last_save_error = ''
                popup.dismiss()
                self.render()
            else:
                self.notice('설정 복구 실패', self.state.error)
        box.add_widget(self.button('백업 후 초기화', reset, True))
        box.add_widget(self.button('취소', popup.dismiss))
        popup.open()


if __name__ == '__main__':
    ToolboxApp().run()
