from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from app.palette import palette
from app.services.cloudflare_transfer import TransferClient, TransferError
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame


class LanRemoteTool(tk.Frame):
    """Cloudflare chat/transfer view; retains the existing saved tool ID."""
    def __init__(self, parent: tk.Widget, app: object) -> None:
        self.colors = palette(app.dark_mode)
        super().__init__(parent, bg=self.colors['panel'])
        self.app = app
        config = getattr(app, 'config_store', None)
        self.endpoint = tk.StringVar(value=config.get('cloudflare_transfer', 'endpoint', default='') if config else '')
        self.nickname = tk.StringVar(value=config.get('cloudflare_transfer', 'name', default='나') if config else '나')
        self.token = tk.StringVar()
        self.room = tk.StringVar()
        self.message = tk.StringVar()
        self.status = tk.StringVar(value='●  서버 미연결')
        self.region = tk.StringVar(value='연결 지역  ·  자동 (Cloudflare 라우팅)')
        self.latency = tk.StringVar(value='응답 시간  ·  —')
        self.security = tk.StringVar(value='연결 대기')
        self.client = None
        self.generation = 0
        self.connecting = self.sending = self.transferring = False
        self.closed = False
        self.events = queue.Queue()
        self.cards = []
        self.chat_rows = []
        self.filter = '전체'
        self._build()
        self.timer = self.after(60, self._drain)

    def _label(self, parent, text=None, variable=None, **kwargs):
        label = tk.Label(parent, text=text, textvariable=variable, bg=parent.cget('bg'), fg=self.colors['text'], font=('Segoe UI', 10), **kwargs)
        return label

    def _entry(self, parent, variable, **kwargs):
        return tk.Entry(parent, textvariable=variable, bg=self.colors['field'], fg=self.colors['text'], insertbackground=self.colors['accent'], relief='flat', font=('Segoe UI', 10), **kwargs)

    def _button(self, parent, text, command, accent=False):
        button = RoundedButton(parent, text, command, self.colors, accent=accent, compact=True, radius=8)
        button.configure(width=max(38, tkfont.Font(family='Segoe UI', size=10, weight='bold').measure(text) + 28))
        return button

    def _panel(self, parent):
        return RoundedFrame(parent, self.colors, self.colors['surface'], self.colors['border'], radius=10, padding=10)

    def _build(self):
        c = self.colors
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
        header = tk.Frame(self, bg=c['panel'])
        header.grid(row=0, column=0, sticky='ew', padx=18, pady=(14, 10))
        tk.Label(header, text='☁', font=('Segoe UI', 38), fg='#ff8614', bg=c['panel']).pack(side='left', padx=(0, 14))
        title = tk.Frame(header, bg=c['panel'])
        title.pack(side='left', fill='x', expand=True)
        tk.Label(title, text='Cloudflare Chat Transfer', font=('Segoe UI', 21, 'bold'), fg=c['text'], bg=c['panel'], anchor='w').pack(fill='x')
        self._label(title, 'Cloudflare를 통한 채팅 및 파일 전송 · 같은 Wi-Fi 없이 연결').pack(anchor='w', pady=(2, 0))

        status = self._panel(self)
        status.grid(row=1, column=0, sticky='ew', padx=18, pady=(0, 8))
        for col in range(4):
            status.body.columnconfigure(col, weight=1)
        self.connection_label = self._label(status.body, variable=self.status)
        self.connection_label.grid(row=0, column=0, sticky='w', padx=6)
        self._label(status.body, variable=self.region).grid(row=0, column=1, sticky='w', padx=6)
        self._label(status.body, variable=self.latency).grid(row=0, column=2, sticky='w', padx=6)
        self._label(status.body, variable=self.security).grid(row=0, column=3, sticky='w', padx=6)
        self._button(status.body, '연결 해제', self.stop).grid(row=0, column=4, padx=(6, 0))

        room = self._panel(self)
        room.grid(row=2, column=0, sticky='ew', padx=18, pady=(0, 8))
        room.body.columnconfigure(1, weight=1)
        self._label(room.body, '채팅방 / 연결 코드').grid(row=0, column=0, padx=(0, 10))
        self.room_entry = self._entry(room.body, self.room, width=20)
        self.room_entry.grid(row=0, column=1, sticky='ew', ipady=8)
        self._button(room.body, '복사', self.copy_room).grid(row=0, column=2, padx=5)
        self._button(room.body, '새 방 만들기', lambda: self.connect(True), True).grid(row=0, column=3, padx=5)
        self._button(room.body, '방 참가', lambda: self.connect(False)).grid(row=0, column=4, padx=5)
        self.options_button = self._button(room.body, '⚙ 연결 옵션', self.options)
        self.options_button.grid(row=0, column=5, padx=(5, 0))

        self.content = tk.Frame(self, bg=c['panel'])
        self.content.grid(row=3, column=0, sticky='nsew', padx=18, pady=(0, 14))
        self.content.columnconfigure(0, weight=3, uniform='transfer')
        self.content.columnconfigure(1, weight=2, uniform='transfer')
        self.content.rowconfigure(0, weight=1)
        self.chat_panel = self._panel(self.content)
        self.chat_panel.grid(row=0, column=0, sticky='nsew', padx=(0, 5))
        left = self.chat_panel.body
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        tabs = tk.Frame(left, bg=c['surface'])
        tabs.grid(row=0, column=0, sticky='ew', pady=(0, 8))
        self.chat_tab = self._button(tabs, '☏  채팅', lambda: self.show_tab('chat'), True)
        self.chat_tab.pack(side='left', fill='x', expand=True)
        self._button(tabs, '↗  파일 전송', lambda: self.show_tab('files')).pack(side='left', fill='x', expand=True)
        self._button(tabs, '☷  전송 기록', lambda: self.show_tab('history')).pack(side='left', fill='x', expand=True)
        chat_box = tk.Frame(left, bg=c['field'])
        chat_box.grid(row=1, column=0, sticky='nsew')
        chat_box.columnconfigure(0, weight=1)
        chat_box.rowconfigure(0, weight=1)
        self.chat_canvas = tk.Canvas(chat_box, bg=c['field'], highlightthickness=0, width=100, height=200)
        self.chat_canvas.grid(row=0, column=0, sticky='nsew')
        scroll = ttk.Scrollbar(chat_box, command=self.chat_canvas.yview)
        scroll.grid(row=0, column=1, sticky='ns')
        self.chat_canvas.configure(yscrollcommand=scroll.set)
        self.chat_body = tk.Frame(self.chat_canvas, bg=c['field'])
        self.chat_window = self.chat_canvas.create_window(0, 0, anchor='nw', window=self.chat_body)
        self.chat_body.bind('<Configure>', lambda _: self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox('all')))
        self.chat_canvas.bind('<Configure>', self._chat_resize)
        self.chat_canvas.bind('<MouseWheel>', lambda e: self.chat_canvas.yview_scroll(-int(e.delta / 120), 'units'))
        self.history = tk.Text(chat_box, bg=c['field'], fg=c['muted'], relief='flat', state='disabled', wrap='word', width=30)
        compose = tk.Frame(left, bg=c['surface'])
        compose.grid(row=2, column=0, sticky='ew', pady=(10, 0))
        compose.columnconfigure(1, weight=1)
        self._button(compose, '＋', self.send_file).grid(row=0, column=0, padx=(0, 6))
        self.message_entry = self._entry(compose, self.message, width=15)
        self.message_entry.grid(row=0, column=1, sticky='ew', ipady=12)
        self.message_entry.bind('<Return>', lambda _: self.send_text())
        self._button(compose, '전송 ➤', self.send_text, True).grid(row=0, column=2, padx=(8, 0))

        self.file_panel = self._panel(self.content)
        self.file_panel.grid(row=0, column=1, sticky='nsew', padx=(5, 0))
        right = self.file_panel.body
        right.columnconfigure(0, weight=1)
        right.rowconfigure(2, weight=1)
        file_header = tk.Frame(right, bg=c['surface'])
        file_header.grid(row=0, column=0, sticky='ew')
        self._label(file_header, '▤  파일 전송').pack(side='left')
        self._button(file_header, '＋ 파일 추가', self.send_file, True).pack(side='right')
        filters = tk.Frame(right, bg=c['surface'])
        filters.grid(row=1, column=0, sticky='ew', pady=8)
        self.filter_buttons = {}
        for name in ('전체', '전송 중', '완료', '실패'):
            button = self._button(filters, name, lambda value=name: self.filter_files(value))
            button.pack(side='left', fill='x', expand=True)
            self.filter_buttons[name] = button
        self.filter_buttons['전체'].set_active(True)
        file_box = tk.Frame(right, bg=c['field'])
        file_box.grid(row=2, column=0, sticky='nsew')
        file_box.rowconfigure(0, weight=1)
        file_box.columnconfigure(0, weight=1)
        self.files_canvas = tk.Canvas(file_box, bg=c['field'], highlightthickness=0, width=100, height=160)
        self.files_canvas.grid(row=0, column=0, sticky='nsew')
        file_scroll = ttk.Scrollbar(file_box, command=self.files_canvas.yview)
        file_scroll.grid(row=0, column=1, sticky='ns')
        self.files_canvas.configure(yscrollcommand=file_scroll.set)
        self.files_body = tk.Frame(self.files_canvas, bg=c['field'])
        self.files_window = self.files_canvas.create_window(0, 0, anchor='nw', window=self.files_body)
        self.files_body.bind('<Configure>', lambda _: self.files_canvas.configure(scrollregion=self.files_canvas.bbox('all')))
        self.files_canvas.bind('<Configure>', lambda e: self.files_canvas.itemconfigure(self.files_window, width=e.width))
        self.files_canvas.bind('<MouseWheel>', lambda e: self.files_canvas.yview_scroll(-int(e.delta / 120), 'units'))
        self._label(self.files_body, '아직 공유된 파일이 없습니다.').pack(pady=20)
        self._button(right, '☁  클릭하여 전송할 파일 선택', self.send_file).grid(row=3, column=0, sticky='ew', pady=(10, 4))
        self._label(right, '파일당 25 MiB · 방당 총 100 MiB · 24시간 후 삭제').grid(row=4, column=0, sticky='w')
        self._label(right, 'HTTPS 전송 · 방 코드는 신뢰하는 사람에게만 공유하세요.').grid(row=5, column=0, sticky='w', pady=(4, 0))
        self.bind('<Configure>', self._resize)
        self._chat('안내', '연결 옵션에서 서버 주소와 인증 토큰을 입력한 뒤 새 방을 만들거나 방 코드로 참가하세요.', False)

    def _resize(self, event):
        if event.widget != self:
            return
        narrow = event.width < 1000
        self.chat_panel.grid_configure(row=0, column=0, columnspan=2 if narrow else 1, padx=(0, 0 if narrow else 5))
        self.file_panel.grid_configure(row=1 if narrow else 0, column=0 if narrow else 1, columnspan=2 if narrow else 1, padx=(0 if narrow else 5, 0), pady=(8 if narrow else 0, 0))
        self.content.rowconfigure(1, weight=1 if narrow else 0)

    def _chat_resize(self, event):
        self.chat_canvas.itemconfigure(self.chat_window, width=event.width)
        for label in self.chat_rows:
            label.configure(wraplength=max(120, int(event.width * .78)))

    def _chat(self, name, text, own, timestamp=None):
        c = self.colors
        row = tk.Frame(self.chat_body, bg=c['field'])
        row.pack(fill='x', padx=10, pady=8)
        stamp = datetime.fromtimestamp(timestamp / 1000).strftime('%H:%M') if timestamp else datetime.now().strftime('%H:%M')
        self._label(row, f'{name}   {stamp}').pack(anchor='e' if own else 'w')
        bubble = tk.Label(row, text=text, justify='left', wraplength=max(120, int(self.chat_canvas.winfo_width() * .78)), bg=c['accent_soft'] if own else c['surface_hover'], fg=c['text'], font=('Segoe UI', 10), padx=12, pady=10)
        bubble.pack(anchor='e' if own else 'w', pady=(4, 0))
        self.chat_rows.append(bubble)
        if len(self.chat_rows) > 500:
            self.chat_rows.pop(0).master.destroy()
        self.chat_canvas.update_idletasks()
        self.chat_canvas.yview_moveto(1)

    def _log(self, text):
        self.history.configure(state='normal')
        self.history.insert('end', f'{datetime.now():%H:%M:%S}  {text}\n')
        if int(self.history.index('end-1c').split('.')[0]) > 500:
            self.history.delete('1.0', '2.0')
        self.history.configure(state='disabled')
        self.history.see('end')

    def show_tab(self, tab):
        self.chat_tab.set_active(tab == 'chat')
        if tab == 'history':
            self.history.grid(row=0, column=0, sticky='nsew')
            self.history.tkraise()
        else:
            self.history.grid_remove()
        if tab == 'files':
            self.file_panel.focus_set()
            self.filter_files('전체')

    def options(self):
        if getattr(self, 'options_window', None) and self.options_window.winfo_exists():
            self.options_window.lift()
            return
        window = tk.Toplevel(self)
        self.options_window = window
        window.title('Cloudflare 연결 옵션')
        window.configure(bg=self.colors['surface'])
        window.transient(self.winfo_toplevel())
        window.columnconfigure(0, weight=1)
        for row, (label, variable, secret) in enumerate((('Workers 서버 주소 (https://…workers.dev)', self.endpoint, False), ('서버 인증 토큰 (SERVICE_TOKEN)', self.token, True), ('채팅 표시 이름', self.nickname, False))):
            self._label(window, label).grid(row=row * 2, column=0, sticky='w', padx=18, pady=(12, 4))
            self._entry(window, variable, width=55, show='•' if secret else '').grid(row=row * 2 + 1, column=0, sticky='ew', padx=18, ipady=8)
        self._label(window, '토큰·방 코드는 디스크에 저장하지 않습니다. 변경 후 다시 연결하세요.').grid(row=6, column=0, padx=18, pady=12)
        self._button(window, '적용', lambda: self._save_options(window), True).grid(row=7, column=0, sticky='e', padx=18, pady=(0, 16))

    def _save_options(self, window):
        try:
            TransferClient(self.endpoint.get(), self.token.get(), self.nickname.get())
        except (ValueError, TransferError) as exc:
            self._log(str(exc))
            return
        config = getattr(self.app, 'config_store', None)
        if config:
            config.set_many({('cloudflare_transfer', 'endpoint'): self.endpoint.get().strip(), ('cloudflare_transfer', 'name'): self.nickname.get().strip()})
        window.destroy()

    def copy_room(self):
        if self.room.get():
            self.clipboard_clear()
            self.clipboard_append(self.room.get())
            self._log('전체 방 코드가 클립보드에 복사되었습니다.')

    def _work(self, task, done, generation=None):
        generation = self.generation if generation is None else generation
        def worker():
            try:
                result, error = task(), None
            except Exception as exc:
                result, error = None, str(exc)
            self.events.put((generation, done, result, error))
        threading.Thread(target=worker, daemon=True).start()

    def connect(self, create):
        if self.connecting:
            return
        try:
            client = TransferClient(self.endpoint.get(), self.token.get(), self.nickname.get())
            invitation = self.room.get().strip()
            if not create:
                client._set_room(invitation)
        except (ValueError, TransferError) as exc:
            self._log(str(exc))
            self.options()
            return
        self.stop()
        for child in self.chat_body.winfo_children():
            child.destroy()
        self.chat_rows.clear()
        for child in self.files_body.winfo_children():
            child.destroy()
        self.cards.clear()
        self._label(self.files_body, '아직 공유된 파일이 없습니다.').pack(pady=20)
        self.client = client
        self.connecting = True
        self.status.set('●  서버 연결 중…')
        generation = self.generation
        def ready(result, error):
            self.connecting = False
            if error:
                self.stop()
                self.status.set('●  연결 실패')
                self._log(error)
                return
            self.room.set(client.invitation)
            self.status.set('●  서버 연결됨')
            self.region.set(f"연결 지역  ·  {result.get('region', '자동')}")
            self.latency.set(f"응답 시간  ·  {result['latency']} ms")
            self.security.set('HTTPS 보안 연결' if client.url.scheme == 'https' else '로컬 개발 HTTP')
            self.connection_label.configure(fg='#17c96b' if client.url.scheme == 'https' else self.colors['warning'])
            self._chat('안내', '방에 연결되었습니다. 방 코드와 서버 인증 토큰을 아는 사람이 참가할 수 있습니다.', False)
            self._log('방 연결 완료 · 생성 후 24시간 유지')
            threading.Thread(target=self._poll, args=(client, generation), daemon=True).start()
        self._work(client.create if create else lambda: client.join(invitation), ready)

    def _poll(self, client, generation):
        failures = 0
        while not client.cancel.is_set():
            started = time.monotonic()
            try:
                batch = client.events()
                self.events.put((generation, self._receive, (batch, round((time.monotonic() - started) * 1000)), None))
                failures = 0
            except Exception as exc:
                if client.cancel.is_set():
                    break
                failures += 1
                self.events.put((generation, self._poll_error, failures, str(exc)))
                if failures >= 3:
                    break
            if client.cancel.wait(3):
                break

    def _poll_error(self, failures, error):
        self._log(f'수신 실패 ({failures}/3): {error}')
        self.status.set('●  연결 확인 중…')
        if failures >= 3:
            self.stop()
            self.status.set('●  연결 끊김 · 다시 참가하세요')

    def _receive(self, result, error):
        batch, latency = result
        self.status.set('●  서버 연결됨')
        self.latency.set(f'응답 시간  ·  {latency} ms')
        for event in batch:
            if event.get('type') == 'chat':
                self._chat(event['name'], event['text'], event['name'] == self.client.name, event.get('time'))
            elif event.get('type') == 'file':
                self._card(event['name'], event['size'], '공유됨', event)
                self._log(f"공유 파일: {event['name']}")

    def _drain(self):
        if self.closed:
            return
        for _ in range(100):
            try:
                generation, done, result, error = self.events.get_nowait()
            except queue.Empty:
                break
            if generation == self.generation:
                done(result, error)
        self.timer = self.after(60, self._drain)

    def _connected(self):
        if not self.client or self.connecting or self.client.cancel.is_set():
            self._log('먼저 방에 연결하세요.')
            return False
        return True

    def send_text(self):
        if not self._connected() or self.sending:
            return
        text = self.message.get()
        if not text.strip():
            return
        self.sending = True
        client = self.client
        def sent(_result, error):
            self.sending = False
            if error:
                self._log(f'메시지 전송 실패: {error}')
            elif self.message.get() == text:
                self.message.set('')
        self._work(lambda: client.send(text), sent)

    def _card(self, name, size, state, event=None):
        if not self.cards:
            for child in self.files_body.winfo_children():
                child.destroy()
        frame = tk.Frame(self.files_body, bg=self.colors['surface_hover'], padx=10, pady=10)
        frame.columnconfigure(0, weight=1)
        self._label(frame, name, anchor='w', wraplength=280).grid(row=0, column=0, sticky='ew')
        label = self._label(frame, f'{size / 1048576:.2f} MiB · {state}', anchor='w')
        label.grid(row=1, column=0, sticky='ew', pady=5)
        bar = ttk.Progressbar(frame, maximum=100)
        bar.grid(row=2, column=0, sticky='ew')
        card = {'frame': frame, 'label': label, 'bar': bar, 'state': state, 'name': name, 'size': size, 'button': None}
        self.cards.append(card)
        if len(self.cards) > 500:
            self.cards.pop(0)['frame'].destroy()
        if event:
            card['button'] = self._button(frame, '다운로드', lambda: self.download(event, card), True)
            card['button'].grid(row=3, column=0, sticky='e', pady=(6, 0))
        self.filter_files(self.filter)
        return card

    def filter_files(self, value):
        self.filter = value
        for name, button in self.filter_buttons.items():
            button.set_active(name == value)
        for card in self.cards:
            card['frame'].pack_forget()
            if value == '전체' or card['state'] == value:
                card['frame'].pack(fill='x', padx=7, pady=6)

    def _transfer(self, client, card, task, on_done=None):
        if self.transferring:
            self._log('현재 전송이 끝난 뒤 다시 시도하세요.')
            return
        self.transferring = True
        card['state'] = '전송 중'
        self.filter_files(self.filter)
        started = time.monotonic()
        last = [0.0]
        generation = self.generation
        def progress(done, total):
            now = time.monotonic()
            if now - last[0] < .1 and done != total:
                return
            last[0] = now
            speed = done / max(.01, now - started)
            self.events.put((generation, lambda values, _: self._progress(card, *values), (done, total, speed), None))
        def complete(_result, error):
            self.transferring = False
            card['state'] = '실패' if error else '완료'
            card['label'].configure(text=f"{card['state']} · {error or '서버 확인 완료'}", wraplength=280)
            if not error:
                card['bar']['value'] = 100
            self._log(f"{card['name']} · {card['state']}" + (f' · {error}' if error else ''))
            self.filter_files(self.filter)
            if on_done:
                on_done()
        self._work(lambda: task(progress), complete)

    def _progress(self, card, done, total, speed):
        card['bar']['value'] = done * 100 / total
        remaining = (total - done) / max(1, speed)
        card['label'].configure(text=f'{done * 100 / total:.0f}% · {speed / 1048576:.1f} MiB/s · 약 {remaining:.0f}초 남음')

    def send_file(self):
        if not self._connected() or self.transferring:
            return
        paths = filedialog.askopenfilenames(parent=self, title='전송할 파일 선택 (각 25 MiB 이하)')
        if not paths:
            return
        client = self.client
        # Upload sequentially without blocking the Tk event loop.
        pending = list(paths)
        def next_file():
            if pending and self.client is client and not client.cancel.is_set():
                path = Path(pending.pop(0))
                try:
                    size = path.stat().st_size
                except OSError as exc:
                    self._log(str(exc))
                    next_file()
                    return
                card = self._card(path.name, size, '전송 중')
                self._transfer(client, card, lambda progress: client.upload(path, progress), next_file)
        next_file()

    def download(self, event, card):
        if not self._connected() or self.transferring:
            return
        safe_name = event['name'].replace('\\', '/').split('/')[-1]
        path = filedialog.asksaveasfilename(parent=self, title='받은 파일 저장', initialfile=safe_name)
        if path:
            client = self.client
            self._transfer(client, card, lambda progress: client.download(event['file'], Path(path), event['size'], progress))

    def stop(self):
        self.generation += 1
        if self.client:
            self.client.cancel.set()
        self.client = None
        self.connecting = self.sending = self.transferring = False
        self.status.set('●  서버 미연결')
        self.region.set('연결 지역  ·  자동 (Cloudflare 라우팅)')
        self.latency.set('응답 시간  ·  —')
        self.security.set('연결 대기')
        self.connection_label.configure(fg=self.colors['muted'])
        for card in self.cards:
            if card['state'] == '전송 중':
                card['state'] = '실패'
                card['label'].configure(text='연결 해제로 전송 취소')
            if card['button']:
                card['button'].destroy()
                card['button'] = None
        self.filter_files(self.filter)

    def destroy(self):
        self.closed = True
        self.stop()
        self.after_cancel(self.timer)
        if getattr(self, 'options_window', None) and self.options_window.winfo_exists():
            self.options_window.destroy()
        super().destroy()


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return LanRemoteTool(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec('network.lan_remote', 'Cloudflare Chat Transfer', '네트워크', build, 20))
