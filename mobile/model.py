"""UI와 Android 의존성이 없는 도구 목록 및 개인화 상태."""
import json
import os
from pathlib import Path
import shutil
import time


MENUS = {'audio': '오디오', 'developer': '개발 도구', 'notes': '메모', 'pc': 'PC 연동'}
TOOLS = {
    'tts': ('TTS', 'audio', '텍스트를 음성으로'),
    'soundboard': ('사운드보드', 'audio', '내 소리를 한곳에서'),
    'converter': ('개발자 변환기', 'developer', '진법 · JSON · Base64'),
    'scratchpad': ('스크래치패드', 'notes', '떠오른 생각을 빠르게'),
    'monitor': ('시스템 모니터', 'pc', '연결한 PC의 상태 확인'),
    'launcher': ('게임 실행기', 'pc', 'PC 게임 원격 실행'),
    'automation': ('자동화 관리', 'pc', 'PC 워크플로 실행과 중지'),
    'chat': ('채팅·파일 전송', 'pc', 'PC와 메시지 및 파일 공유'),
}
THEMES = {
    'dark': dict(bg='#03071e', panel='#100e23', border='#370617', text='#fff8ef',
                 muted='#b9b4c9', accent='#ffba08', secondary='#dc2f02', active='#9d0208', ink='#ffffff'),
    'light': dict(bg='#fffaf7', panel='#fff0ef', border='#f7c9d2', text='#170b39',
                  muted='#6d597b', accent='#9e0059', secondary='#ff5400', active='#ff0054', ink='#ffffff'),
    'green': dict(bg='#fefae0', panel='#f2edce', border='#c4c59c', text='#283618',
                  muted='#606c38', accent='#bc6c25', secondary='#dda15e', active='#606c38', ink='#fefae0'),
}


class State:
    def __init__(self, path):
        self.path = Path(path)
        self.theme = 'dark'
        self.counts = {}
        self.pins = {}
        self.error = ''
        self.readable = True
        self.load()

    def load(self):
        try:
            if self.path.stat().st_size > 262_144:
                raise ValueError('설정 파일 크기 제한 초과')
            data = json.loads(self.path.read_text(encoding='utf-8'))
            if not isinstance(data, dict):
                raise ValueError('설정 형식 오류')
            theme = data.get('theme')
            self.theme = theme if isinstance(theme, str) and theme in THEMES else 'dark'
            counts = data.get('counts', {})
            self.counts = {k: min(v, 10**9) for k, v in counts.items()
                           if k in {*MENUS, *TOOLS} and type(v) is int and v >= 0} if isinstance(counts, dict) else {}
            pins = data.get('pins', {})
            if isinstance(pins, dict):
                used = set()
                for slot, valid in [('menu1', MENUS), ('menu2', MENUS), ('tool1', TOOLS)]:
                    value = pins.get(slot)
                    if isinstance(value, str) and value in valid and value not in used:
                        self.pins[slot] = value
                        used.add(value)
        except FileNotFoundError:
            pass
        except (OSError, ValueError, TypeError):
            self.readable = False
            self.error = '설정을 읽지 못해 자동 저장을 중단했습니다. 설정에서 백업 후 초기화해 주세요.'

    def save(self):
        if not self.readable:
            return False
        temporary = self.path.with_suffix('.tmp')
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(dict(version=1, theme=self.theme,
                                                  counts=self.counts, pins=self.pins),
                                            ensure_ascii=False, indent=2), encoding='utf-8')
            os.replace(temporary, self.path)
            self.error = ''
            return True
        except OSError:
            self.error = '설정 저장에 실패했습니다. 저장 공간을 확인해 주세요.'
            return False

    def reset(self):
        """UI 확인 후에만 호출하며 기존 파일을 별도 보존한다."""
        try:
            if self.path.exists():
                backup = self.path.with_name(f'{self.path.stem}.before-reset-{time.time_ns()}.json')
                shutil.copyfile(self.path, backup)
        except OSError:
            self.error = '기존 설정을 백업하지 못해 초기화하지 않았습니다.'
            return False
        self.theme, self.counts, self.pins = 'dark', {}, {}
        self.readable = True
        return self.save()

    def visit(self, key):
        if key in MENUS or key in TOOLS:
            self.counts[key] = min(self.counts.get(key, 0) + 1, 10**9)

    def tabs(self):
        # 먼저 고정값을 예약하여 앞쪽 자동 추천이 뒤쪽 고정값을 차지하지 않는다.
        used = set(self.pins.values())
        result = dict(self.pins)
        for slot, choices in [('menu1', MENUS), ('menu2', MENUS), ('tool1', TOOLS)]:
            if slot not in result:
                ranked = sorted(choices, key=lambda k: -self.counts.get(k, 0))
                result[slot] = next(k for k in ranked if k not in used)
                used.add(result[slot])
        return result

    def pin(self, slot, key):
        choices = TOOLS if slot == 'tool1' else MENUS
        if slot not in ('menu1', 'menu2', 'tool1') or key not in choices:
            raise ValueError('고정할 수 없는 탭입니다.')
        for other, value in list(self.pins.items()):
            if value == key and other != slot:
                del self.pins[other]
        self.pins[slot] = key

    def search(self, query):
        query = query.strip().casefold()
        return [key for key, (name, menu, description) in TOOLS.items()
                if query in f'{name} {MENUS[menu]} {description} {key}'.casefold()]
