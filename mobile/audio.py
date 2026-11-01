"""사운드보드 제어와 Android/데스크톱 재생 연결."""
import json
import threading
import uuid
try:
    from .audio_library import AudioLibrary
except ImportError:
    from audio_library import AudioLibrary


class SoundboardController:
    def __init__(self, root, factory, changed=None, dispatch=None):
        self.library = AudioLibrary(root)
        self.factory, self.backend = factory, None
        self.changed = changed or (lambda catalogue=False: None)
        self.dispatch = dispatch or (lambda call: call())
        self.busy, self.closed = False, False
        self.pending = None
        self.active_id = ''
        self.status = self.library.error or '오디오 파일을 가져와 주세요.'

    def _backend(self):
        if self.backend is None:
            self.backend = self.factory(self.event)
        return self.backend

    def choose_android(self):
        if self.closed or self.busy:
            return
        try:
            self.pending = self.library.staging_path()
            self.busy = True
            self.status = '시스템 선택창에서 오디오를 선택해 주세요.'
            self._backend().choose(self.pending)
        except Exception:
            self.status = self.library.error or '파일 선택창을 열지 못했습니다.'
            self.busy = False
            self.pending = None
        self.changed()

    def import_file(self, path):
        if self.closed or self.busy:
            return
        self.busy, self.status = True, '오디오를 앱 저장소로 복사하고 있습니다.'
        self.changed()
        def worker():
            try:
                item = self.library.import_file(path,lambda: self.closed)
                message = f"등록됨 · {item['name']}"
            except (OSError, ValueError):
                message = self.library.error or '파일을 가져오지 못했습니다. 형식·25MiB 제한·저장 공간을 확인해 주세요.'
            def finish():
                self.busy = False
                if not self.closed:
                    self.status = message
                    self.changed(catalogue=True)
            self.dispatch(finish)
        self.worker = threading.Thread(target=worker,daemon=True)
        self.worker.start()

    def event(self, event, data):
        if self.closed:
            return
        if event in ('imported','import_cancelled','import_error'):
            if self.pending is None:
                return
            try:
                if event == 'imported':
                    if str(self.pending) != data.get('path'):
                        raise ValueError()
                    item = self.library.commit_staging(self.pending,data.get('name',''),data.get('mime',''))
                    self.status = f"등록됨 · {item['name']}"
                else:
                    self.status = '파일 선택을 취소했습니다.' if event == 'import_cancelled' else data.get('message','파일을 가져오지 못했습니다.')
            except (OSError, ValueError):
                self.status = '등록하지 못했습니다. 오디오 형식·저장 공간을 확인해 주세요.'
            finally:
                try:
                    self.pending.unlink(missing_ok=True)
                except OSError:
                    pass
                self.pending, self.busy = None, False
            self.changed(catalogue=True)
            return
        if data.get('id') != self.active_id or not self.active_id:
            return
        self.status = data.get('message','재생 상태 변경')
        if event in ('done','stopped','error'):
            self.active_id = ''
        self.changed()

    def play(self, key):
        if self.closed:
            return
        try:
            path = self.library.path_for(key)
            self.active_id = uuid.uuid4().hex
            self.status = '오디오를 준비하고 있습니다.'
            self._backend().play(str(path),self.active_id)
        except Exception:
            self.active_id = ''
            self.status = '재생하지 못했습니다. 파일과 이 기기의 지원 형식을 확인해 주세요.'
        self.changed()

    def stop(self):
        self.active_id = ''
        if self.backend:
            try:
                self.backend.stop()
                self.status = '재생을 중지했습니다.'
            except Exception:
                self.status = '재생 중지 요청에 실패했습니다.'
        self.changed()

    def remove(self, key):
        if self.closed or self.busy:
            return
        self.stop()
        try:
            self.library.remove(key)
            self.status = self.library.error or '앱에 보관한 사운드를 제거했습니다. 원본 파일은 유지됩니다.'
        except (OSError, ValueError):
            self.status = '파일 제거에 실패했습니다. 목록과 저장 공간을 확인해 주세요.'
        self.changed(catalogue=True)

    def close(self):
        self.closed, self.active_id = True, ''
        if self.backend:
            self.backend.close()
        if self.pending:
            try:
                self.pending.unlink(missing_ok=True)
            except OSError:
                pass


class KivyAudioBackend:
    def __init__(self, callback):
        self.callback, self.sound = callback, None

    def play(self, path, request):
        from kivy.core.audio import SoundLoader
        self.stop()
        sound = SoundLoader.load(path)
        if sound is None:
            raise ValueError('지원되지 않는 오디오')
        self.sound = sound
        sound.bind(on_stop=lambda *_: self.callback('done',dict(id=request,message='재생을 마쳤습니다.')))
        sound.play()
        if sound.state != 'play':
            raise RuntimeError('오디오 출력 시작 실패')
        self.callback('playing',dict(id=request,message='재생 중입니다.'))

    def stop(self):
        if self.sound:
            self.sound.stop()
            self.sound.unload()
            self.sound = None

    def close(self):
        self.stop()


class AndroidAudioBackend:
    REQUEST = 21817

    def __init__(self, callback):
        from kivy.clock import Clock
        from jnius import autoclass, PythonJavaClass, java_method
        from android import activity
        self.callback, self.pending, self.closed = callback, None, False
        self.activity = autoclass('org.kivy.android.PythonActivity').mActivity
        backend = self
        class Listener(PythonJavaClass):
            __javainterfaces__ = ['io/seoul2line/toolbox/AudioBridge$Listener']
            __javacontext__ = 'app'

            @java_method('(Ljava/lang/String;Ljava/lang/String;)V')
            def onEvent(self, event, payload):
                data, event = json.loads(str(payload)), str(event)
                Clock.schedule_once(lambda _: callback(event,data) if not backend.closed else None,0)
        self.listener = Listener()
        self.bridge = autoclass('io.seoul2line.toolbox.AudioBridge').create(self.activity,self.listener)
        activity.bind(on_activity_result=self.result)

    def choose(self, destination):
        from android.runnable import run_on_ui_thread
        from jnius import autoclass
        self.pending = str(destination)
        @run_on_ui_thread
        def launch():
            try:
                Intent = autoclass('android.content.Intent')
                intent = Intent(Intent.ACTION_OPEN_DOCUMENT)
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                intent.setType('audio/*')
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                self.activity.startActivityForResult(intent,self.REQUEST)
            except Exception:
                self.deliver('import_error',dict(message='파일 선택창을 열지 못했습니다.'))
        launch()

    def deliver(self, event, data):
        from kivy.clock import Clock
        Clock.schedule_once(lambda _: self.callback(event,data) if not self.closed else None,0)

    def result(self, request, result, intent):
        if request != self.REQUEST or self.closed or self.pending is None:
            return
        destination, self.pending = self.pending, None
        if result != -1 or intent is None or intent.getData() is None:
            self.deliver('import_cancelled',{})
        else:
            self.bridge.copyDocument(str(intent.getData().toString()),destination)

    def play(self, path, request):
        self.bridge.play(path,request)

    def stop(self):
        self.bridge.stop()

    def close(self):
        from android import activity
        self.closed = True
        activity.unbind(on_activity_result=self.result)
        self.bridge.close()
