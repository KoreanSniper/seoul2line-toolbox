"""Independent WASAPI shared-mode streams; never calls Tk from a worker."""
from contextlib import contextmanager
import ctypes
import queue
import sys
import threading
import time


@contextmanager
def audio_thread():
    # COM initialization is per thread, including enumeration and each player.
    initialized = False
    if sys.platform == "win32":
        hr = ctypes.windll.ole32.CoInitializeEx(None, 0)
        initialized = hr in (0, 1)
        if hr not in (0, 1, -2147417850):
            raise OSError(f"오디오 COM 초기화 실패: {hr}")
    try:
        yield
    finally:
        if initialized:
            ctypes.windll.ole32.CoUninitialize()


class AudioDriver:
    def devices(self):
        import soundcard as sc
        with audio_thread():
            return [{"id": str(s.id), "name": s.name, "channels": s.channels} for s in sc.all_speakers()]

    def validate(self, path):
        import soundfile as sf
        with sf.SoundFile(str(path)) as sound:
            if sound.frames <= 0 or sound.samplerate <= 0:
                raise ValueError("비어 있는 오디오 파일입니다.")
            # Decode the entire copied file, in bounded memory, before committing.
            while len(sound.read(65536, dtype="float32", always_2d=True)):
                pass

    def play(self, path, output, ready, start, cancel, gain):
        import soundcard as sc
        with audio_thread():
            import soundfile as sf
            import numpy as np
            # Exact ID lookup only: soundcard.get_speaker also fuzzy-matches names.
            speaker = next((s for s in sc.all_speakers() if str(s.id) == output["id"]), None)
            if speaker is None:
                raise ValueError(f"연결되지 않은 출력 장치: {output['name']}. 개인설정에서 다시 선택하세요.")
            channels = min(2, speaker.channels)
            with sf.SoundFile(str(path)) as sound:
                # Shared WASAPI converts the requested rate to each endpoint's mix
                # format. Mono is duplicated; multichannel inputs are downmixed.
                frames = max(128, sound.samplerate // 50)
                with speaker.player(samplerate=sound.samplerate, channels=channels, blocksize=frames * 2) as player:
                    ready.set()
                    while not start.wait(.02):
                        if cancel.is_set():
                            return
                    while not cancel.is_set():
                        block = sound.read(frames, dtype="float32", always_2d=True)
                        if not len(block):
                            break
                        if block.shape[1] > 2 or channels == 1:
                            block = block.mean(axis=1, keepdims=True)
                        if channels == 2 and block.shape[1] == 1:
                            block = np.repeat(block, 2, axis=1)
                        player.play(block * gain(output["id"]))
                    # play() returns before the final buffer has finished.
                    while not cancel.is_set() and player.currentpadding > 0:
                        cancel.wait(.005)


class SoundboardAudio:
    def __init__(self, driver=None):
        self.driver = driver or AudioDriver()
        self.events = queue.Queue()
        self.commands = queue.Queue()
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.generation = 0
        self.current = None
        self.closed = False
        self.volume = 1.0
        self.gains = {}
        self.worker = threading.Thread(target=self._run, daemon=True, name="soundboard-controller")
        self.worker.start()

    def volumes(self, volume, outputs):
        with self.lock:
            self.volume = volume / 100
            self.gains = {o["id"]: o["volume"] / 100 for o in outputs}

    def gain(self, identity):
        with self.lock:
            return self.volume * self.gains.get(identity, 0)

    def stop(self):
        with self.lock:
            self.cancel.set()
            self.generation += 1
            self.current = None

    def toggle(self, identity, path, outputs):
        with self.lock:
            same = identity == self.current
            self.cancel.set()
            self.generation += 1
            self.current = None if same else identity
            if not same and not self.closed:
                self.cancel = threading.Event()
                self.commands.put((self.generation, identity, path, outputs, self.cancel))

    def close(self):
        self.stop()
        self.closed = True
        self.commands.put(None)

    def _run(self):
        while True:
            command = self.commands.get()
            if command is None:
                return
            generation, identity, path, outputs, cancel = command
            if cancel.is_set():
                continue
            start = threading.Event()
            ready_events, workers = [], []

            def run(output, ready):
                try:
                    if not cancel.is_set():
                        self.driver.play(path, output, ready, start, cancel, self.gain)
                except Exception as exc:
                    self.events.put((generation, "error", str(exc)))
                finally:
                    ready.set()

            for output in outputs:
                ready = threading.Event()
                thread = threading.Thread(target=run, args=(output, ready), daemon=True, name="soundboard-output")
                ready_events.append(ready)
                workers.append(thread)
                thread.start()
            # Both independent streams are opened before a shared start signal.
            # A failed endpoint marks itself ready and cannot block its peer.
            for ready in ready_events:
                deadline = time.monotonic() + 3
                while not ready.wait(.02):
                    if cancel.is_set() or time.monotonic() >= deadline:
                        break
            start.set()
            for thread in workers:
                thread.join()
            with self.lock:
                if generation == self.generation:
                    self.current = None
            self.events.put((generation, "done", identity))
