"""플랫폼 독립 TTS 상태 및 지연 로딩 Android 연결."""
import json
import uuid


class SpeechController:
    def __init__(self, factory=None, changed=None):
        self.factory, self.changed = factory, changed or (lambda catalogue=False: None)
        self.backend = None
        self.engines, self.voices = [], []
        self.voice = ''
        self.engine = ''
        self.ready = False
        self.closed = False
        self.active_id = ''
        self.status = 'Android 기기에서 사용할 수 있는 기능입니다.' if factory is None else '음성 엔진을 준비해 주세요.'

    def connect(self, engine=''):
        if self.closed or self.factory is None:
            return
        self.active_id, self.ready, self.voices, self.voice = '', False, [], ''
        self.engine, self.status = engine, '음성 엔진을 준비하고 있습니다.'
        try:
            if self.backend is None:
                self.backend = self.factory(self.event)
            self.backend.initialize(engine)
        except Exception:
            self.status = '음성 엔진 연결에 실패했습니다. 다시 준비해 주세요.'
        self.changed(catalogue=True)

    def event(self, event, payload):
        if self.closed:
            return
        if event == 'catalogue':
            self.engines = payload.get('engines', [])
            self.voices = payload.get('voices', [])
            self.ready = bool(payload.get('ready') and self.voices)
            self.voice = self.voices[0]['id'] if self.voices else ''
            self.status = payload.get('message', '음성 목록을 확인해 주세요.')
            self.changed(catalogue=True)
            return
        request = payload.get('id', '')
        if request and request != self.active_id:
            return
        self.status = payload.get('message', '음성 상태가 변경되었습니다.')
        if event in ('error', 'done', 'stopped'):
            self.active_id = ''
            if event == 'error' and not request:
                self.ready = False
        self.changed()

    def speak(self, text, rate=1.0):
        if self.closed or not self.ready or not self.backend:
            self.status = '사용 가능한 한국어 오프라인 음성을 먼저 준비해 주세요.'
        elif not text.strip():
            self.status = '읽을 내용을 입력해 주세요.'
        elif len(text.encode('utf-16-le', errors='surrogatepass')) // 2 > 4000:
            self.status = '읽기 입력은 UTF-16 기준 4,000자까지 지원합니다.'
        elif not any(v['id'] == self.voice for v in self.voices):
            self.status = '목록에서 음성을 선택해 주세요.'
        else:
            try:
                rate = float(rate)
                if not 0.5 <= rate <= 2.0:
                    raise ValueError()
                self.active_id = uuid.uuid4().hex
                self.status = '읽기를 요청했습니다.'
                self.backend.speak(text, self.voice, rate, self.active_id)
            except Exception:
                self.active_id = ''
                self.status = '읽기 요청에 실패했습니다. 속도와 엔진 상태를 확인해 주세요.'
        self.changed()

    def stop(self):
        self.active_id = ''
        try:
            if self.backend:
                self.backend.stop()
            self.status = '읽기를 중지했습니다.' if self.factory else 'Android 기기에서 사용할 수 있는 기능입니다.'
        except Exception:
            self.status = '음성 엔진에 중지 요청을 보내지 못했습니다.'
        self.changed()

    def close(self):
        self.closed, self.ready, self.active_id = True, False, ''
        try:
            if self.backend:
                self.backend.close()
        finally:
            self.backend = None


class AndroidSpeechBackend:
    def __init__(self, callback):
        from kivy.clock import Clock
        from jnius import autoclass, PythonJavaClass, java_method
        self.session = ''
        backend = self
        class Listener(PythonJavaClass):
            __javainterfaces__ = ['io/seoul2line/toolbox/SpeechBridge$Listener']
            __javacontext__ = 'app'

            @java_method('(Ljava/lang/String;Ljava/lang/String;)V')
            def onEvent(self, event, payload):
                event, data = str(event), json.loads(str(payload))
                Clock.schedule_once(lambda _: callback(event, data) if data.get('session') == backend.session else None, 0)
        self.listener = Listener()
        activity = autoclass('org.kivy.android.PythonActivity').mActivity
        self.bridge = autoclass('io.seoul2line.toolbox.SpeechBridge').create(activity, self.listener)

    def initialize(self, engine):
        self.session = uuid.uuid4().hex
        self.bridge.initialize(engine, self.session)

    def speak(self, text, voice, rate, request):
        self.bridge.speak(text, voice, rate, request)

    def stop(self):
        self.bridge.stop()

    def close(self):
        self.bridge.close()
