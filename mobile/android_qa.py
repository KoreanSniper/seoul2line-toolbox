"""명시적으로 요청한 디버그 APK에서만 실행하는 격리된 Android 검사."""
import json
from pathlib import Path
import re
import traceback
import wave
from kivy.clock import Clock

NOTE = 'Android 프로세스 종료 후 복원 검사'
PINS = {'menu1':'notes','menu2':'pc','tool1':'converter'}


def check(condition, message='Android 검사 조건을 충족하지 못했습니다.'):
    # APK의 -OO 바이트컴파일에서도 검사 조건을 유지한다.
    if not condition:
        raise AssertionError(message)


def requested():
    from jnius import autoclass
    activity = autoclass('org.kivy.android.PythonActivity').mActivity
    intent = activity.getIntent()
    if not (activity.getApplicationInfo().flags & 2) or not intent.getBooleanExtra('s2_smoke_test',False):
        return None
    run = str(intent.getStringExtra('s2_smoke_run') or '')
    phase = int(intent.getIntExtra('s2_smoke_phase',1))
    if not re.fullmatch('[0-9a-f]{12,32}',run) or phase not in (1,2):
        return None
    return dict(run=run,phase=phase)


class AndroidSmoke:
    def __init__(self, app, request):
        self.app, self.request = app, request
        self.root = Path(app.user_data_dir) / 'android-qa' / request['run']
        self.root.mkdir(parents=True,exist_ok=True)
        self.checks = []
        self.deadline = 0
        self.index = 0
        self.finished = False
        self.steps = [self.restored] if request['phase']==2 else [
            self.dark_home,self.light_home,self.green_home,self.navigation,self.personalize,
            self.converter,self.note,self.import_audio,self.wait_audio_import,self.play_audio,
            self.wait_audio_complete,self.start_tts,self.wait_tts,self.complete_home]

    def start(self):
        Clock.schedule_once(self.step,1)

    def step(self, _):
        if self.finished:
            return
        try:
            if self.index == len(self.steps):
                self.finish('passed')
                return
            complete = self.steps[self.index]()
            if complete is not False:
                self.index += 1
                self.deadline = 0
            Clock.schedule_once(self.step,.5)
        except Exception:
            self.finish('failed',traceback.format_exc())

    def wait(self, condition, timeout=20):
        if condition:
            return True
        if not self.deadline:
            self.deadline = Clock.get_time()+timeout
        if Clock.get_time() >= self.deadline:
            raise AssertionError('Android 비동기 처리 시간 초과')
        return False

    def capture(self, name):
        Clock.schedule_once(lambda _: self.app.root.export_to_png(str(self.root/name)),.2)

    def dark_home(self):
        check(len(self.app.nav_buttons)==5,'하단 탭이 5개가 아닙니다.')
        self.app.theme('dark')
        self.app.go('home')
        self.capture('home-dark.png')
        self.checks.append('android_home_five_tabs')

    def light_home(self):
        self.app.theme('light')
        self.capture('home-light.png')

    def green_home(self):
        self.app.theme('green')
        self.capture('home-green.png')
        self.checks.append('three_themes')

    def navigation(self):
        for slot in ('menu1','menu2','home','tool1','settings'):
            expected = self.app.state.tabs().get(slot,slot)
            self.app.nav_buttons[slot].dispatch('on_release')
            check(self.app.page == expected,f'{slot} 탭 이동 실패')
        self.app.back(None,27)
        check(self.app.page == 'home','뒤로 가기 실패')
        self.checks.append('five_tab_bindings_and_back')

    def personalize(self):
        for slot,key in PINS.items():
            self.app.state.pin(slot,key)
        self.app.persist()
        check(self.app.state.tabs()==PINS,'탭 고정 실패')
        self.checks.append('personalization_saved')

    def converter(self):
        self.app.go('converter')
        self.app.converter_input.text = '{"도구":"Android", "정수":12345678901234567890}'
        self.app.run_converter()
        check('12345678901234567890' in self.app.converter_output.text,'변환 정밀도 손실')
        check('도구' in self.app.converter_output.text,'한국어 변환 결과 누락')
        self.checks.append('offline_converter')

    def note(self):
        self.app.go('scratchpad')
        self.app.note_input.text = NOTE
        self.app.go('home')
        check(self.app.scratchpad.path.read_text(encoding='utf-8')==NOTE,'메모 저장 실패')
        self.checks.append('note_saved_on_navigation')

    def import_audio(self):
        source = self.root/'qa-silence.wav'
        with wave.open(str(source),'wb') as output:
            output.setparams((1,2,8000,0,'NONE','not compressed'))
            output.writeframes(b'\x00\x00'*4000)
        self.app.go('soundboard')
        self.app.soundboard.import_file(source)

    def wait_audio_import(self):
        if not self.wait(not self.app.soundboard.busy):
            return False
        check(len(self.app.soundboard.library.items)==1,'오디오 등록 실패')
        self.checks.append('android_local_audio_import')

    def play_audio(self):
        self.app.soundboard.play(self.app.soundboard.library.items[0]['id'])

    def wait_audio_complete(self):
        status = self.app.soundboard.status
        if '실패' in status or '못했습니다' in status or '없는 오디오' in status:
            raise AssertionError(status)
        if not self.wait(status=='재생을 마쳤습니다.'):
            return False
        check(not self.app.soundboard.active_id,'오디오 완료 상태 갱신 실패')
        self.checks.append('android_mediaplayer_completion')

    def start_tts(self):
        self.app.go('tts')
        self.app.speech.connect()

    def wait_tts(self):
        if not self.wait(self.app.speech.catalogue_received):
            return False
        check(self.app.speech.backend is not None,'네이티브 TTS 연결 실패')
        check(self.app.speech.ready == bool(self.app.speech.voices),'TTS 준비 상태 불일치')
        self.checks.append('android_tts_catalogue' if self.app.speech.ready else 'android_tts_no_offline_voice_handled')
        self.capture('tts-catalogue.png')

    def complete_home(self):
        self.app.go('home')
        check(not self.app.speech.active_id,'화면 이동 시 TTS 중지 실패')
        check(not self.app.soundboard.active_id,'화면 이동 시 오디오 중지 실패')
        self.capture('home-final.png')

    def restored(self):
        check(self.app.state.theme=='green','테마 복원 실패')
        check(self.app.state.pins==PINS,'고정값 복원 실패')
        check(self.app.state.tabs()==PINS,'하단 탭 복원 실패')
        check(self.app.scratchpad.text==NOTE,'메모 복원 실패')
        check(len(self.app.soundboard.library.items)==1,'오디오 목록 복원 실패')
        check(self.app.soundboard.library.path_for(self.app.soundboard.library.items[0]['id']).is_file(),'오디오 파일 복원 실패')
        check(len(self.app.nav_buttons)==5,'복원 후 하단 탭 누락')
        self.capture('home-restored.png')
        self.checks.append('real_process_restart_theme_pins_note_audio')

    def finish(self, status, error=''):
        self.finished = True
        report = dict(status=status,phase=self.request['phase'],checks=self.checks,error=error,
                      native_tts_voice_count=len(self.app.speech.voices),
                      width=self.app.root.width,height=self.app.root.height,
                      isolated_data=str(self.app.data_root))
        target = self.root / f"phase-{self.request['phase']}.json"
        temporary = target.with_suffix('.tmp')
        temporary.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(target)
        print('S2_ANDROID_QA_'+status.upper(),json.dumps(report,ensure_ascii=False))
