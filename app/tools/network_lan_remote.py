from __future__ import annotations

from tkinter import simpledialog
import socket
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from app.palette import palette
from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame
from app.config import APP_DIR


PORT_DEFAULT = 5000
SAVE_DIR = APP_DIR / "received"


def send_packet(sock: socket.socket, data: bytes) -> None:
    sock.sendall(len(data).to_bytes(4, "big"))
    sock.sendall(data)


def recv_exact(sock: socket.socket, size: int) -> bytes | None:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            return None
        data += chunk
    return data


def recv_packet(sock: socket.socket) -> bytes | None:
    # 먼저 4바이트 길이 헤더를 읽고, 그 길이만큼 본문을 조립해 반환한다.
    # 패킷이 완성되지 않으면 None을 반환해 호출부가 종료를 처리하게 한다.
    length_data = recv_exact(sock, 4)
    if length_data is None:
        return None
    return recv_exact(sock, int.from_bytes(length_data, "big"))


class LanRemoteTool(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.host = tk.StringVar(value=self.local_ip())
        self.port = tk.IntVar(value=PORT_DEFAULT)
        self.target = tk.StringVar(value=self.local_ip())
        self.allow_commands = tk.BooleanVar(value=False)
        self.server_socket: socket.socket | None = None
        self.client_socket: socket.socket | None = None
        self.connection: socket.socket | None = None
        self.running = False
        self._build()

    def destroy(self) -> None:
        self.stop()
        super().destroy()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 10))
        tk.Label(header, text="Same-WiFi LAN 통합", font=("Segoe UI", 20, "bold"), fg=colors["text"], bg=colors["panel"]).pack(anchor="w")
        tk.Label(header, text="기존 LAN 원격 도구의 텍스트/파일/명령 패킷 구조를 Toolbox UI로 흡수했습니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 0))

        controls = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=12)
        controls.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 10))
        for column in range(6):
            controls.body.columnconfigure(column, weight=1 if column in (1, 3) else 0)
        self._entry(controls.body, "내 IP", self.host, 0, 0)
        self._entry(controls.body, "포트", self.port, 0, 2)
        self._entry(controls.body, "대상 IP", self.target, 1, 0)
        tk.Checkbutton(controls.body, text="받은 명령 실행 허용", variable=self.allow_commands, bg=colors["surface"], fg=colors["muted"], selectcolor=colors["field"], activebackground=colors["surface"], activeforeground=colors["text"]).grid(row=1, column=2, columnspan=2, sticky="w", padx=8)
        RoundedButton(controls.body, "서버 시작", self.start_server, colors, accent=True, compact=True, radius=10).grid(row=0, column=4, padx=6)
        RoundedButton(controls.body, "클라이언트 연결", self.connect_client, colors, compact=True, radius=10).grid(row=0, column=5, padx=6)
        RoundedButton(controls.body, "중지", self.stop, colors, compact=True, radius=10).grid(row=1, column=5, padx=6, pady=(8, 0))

        panel = RoundedFrame(self, colors, colors["surface"], colors["border"], radius=16, padding=12)
        panel.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 18))
        panel.body.columnconfigure(0, weight=1)
        panel.body.rowconfigure(1, weight=1)
        send_bar = tk.Frame(panel.body, bg=colors["surface"])
        send_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        send_bar.columnconfigure(0, weight=1)
        self.message = tk.StringVar()
        for column in range(3):
            send_bar.columnconfigure(column, weight=1)
        tk.Entry(send_bar, textvariable=self.message, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0).grid(row=0, column=0, columnspan=3, sticky="ew", ipady=8)
        RoundedButton(send_bar, "텍스트 전송", self.send_text, colors, accent=True, compact=True, radius=10).grid(row=1, column=0, sticky="ew", padx=(0, 4), pady=(8, 0))
        RoundedButton(send_bar, "파일 전송", self.send_file, colors, compact=True, radius=10).grid(row=1, column=1, sticky="ew", padx=4, pady=(8, 0))
        RoundedButton(send_bar, "명령 전송", self.send_command, colors, compact=True, radius=10).grid(row=1, column=2, sticky="ew", padx=(4, 0), pady=(8, 0))
        self.log = tk.Text(panel.body, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0, wrap="word", font=("Consolas", 10))
        self.log.grid(row=1, column=0, sticky="nsew")

    def _entry(self, parent: tk.Widget, label: str, variable: tk.Variable, row: int, column: int) -> None:
        colors = palette(self.app.dark_mode)
        tk.Label(parent, text=label, fg=colors["muted"], bg=colors["surface"], font=("Segoe UI", 9, "bold")).grid(row=row, column=column, sticky="w", padx=(0, 6), pady=4)
        tk.Entry(parent, textvariable=variable, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], relief="flat", bd=0).grid(row=row, column=column + 1, sticky="ew", ipady=7, pady=4)

    def start_server(self) -> None:
        if self.running:
            return
        self.running = True
        threading.Thread(target=self._server_worker, daemon=True).start()

    def _server_worker(self) -> None:
        # accept()와 recv()처럼 오래 대기할 수 있는 작업을 별도 스레드에서 실행한다.
        # _append()는 after()를 이용해 결과를 Tkinter 메인 스레드로 전달한다.
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((self.host.get(), int(self.port.get())))
            self.server_socket.listen(1)
            self._append("연결 대기 중...\n")
            self.connection, addr = self.server_socket.accept()
            self._append(f"연결됨: {addr}\n")
            next_mode = None
            while self.running:
                data = recv_packet(self.connection)
                if data is None:
                    break
                if next_mode == "file_name":
                    filename = data.decode("utf-8", errors="replace").split(".")[-1]
                    next_mode = "file"
                elif next_mode == "file":
                    SAVE_DIR.mkdir(parents=True, exist_ok=True)
                    path = SAVE_DIR / f"file_{int(time.time())}.{filename}"
                    path.write_bytes(data)
                    self._append(f"파일 저장: {path}\n")
                    next_mode = None
                elif next_mode == "cmd":
                    command = data.decode("utf-8", errors="replace")
                    if self.allow_commands.get():
                        result = subprocess.run(command, shell=True, capture_output=True, text=True, encoding="utf-8", errors="replace")
                        self._append(f"명령 실행: {command}\n{result.stdout}{result.stderr}\n")
                    else:
                        self._append(f"명령 수신 차단됨: {command}\n")
                    next_mode = None
                else:
                    text = data.decode("utf-8", errors="replace")
                    if text == "<img>" or text == "<file>":
                        next_mode = "file_name"
                    elif text == "<cmd>":
                        next_mode = "cmd"
                    else:
                        self._append(f"텍스트: {text}\n")
        except Exception as exc:
            self._append(f"서버 오류: {exc}\n")
        finally:
            self.running = False

    def connect_client(self) -> None:
        if self.client_socket:
            return
        try:
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.connect((self.target.get(), int(self.port.get())))
            self._append("클라이언트 연결됨\n")
        except Exception as exc:
            # 연결 실패를 예외 전파 대신 Text 위젯 로그에 표시하고 재시도할 수 있게 한다.
            self.client_socket = None
            self._append(f"연결 실패: {exc}\n")

    def active_socket(self) -> socket.socket | None:
        return self.client_socket or self.connection

    def send_text(self) -> None:
        sock = self.active_socket()
        if not sock:
            self._append("연결이 없습니다.\n")
            return
        text = simpledialog.askstring("보낼 메시지","보낼 메시지를 입력해주세요")
        if text:
            send_packet(sock, text.encode("utf-8"))
            self._append(f"보냄: {text}\n")
        else:
            self._append(f"취소됨\n")

    def send_command(self) -> None:
        sock = self.active_socket()
        if not sock:
            self._append("연결이 없습니다.\n")
            return
        text = simpledialog.askstring("보낼 명령어","보낼 명령어를 입력해주세요")
        if text:
            send_packet(sock, b"<cmd>")
            send_packet(sock, text.encode("utf-8"))
            self._append(f"명령 전송됨:{self.message.get()}\n")
        else:
            self._append(f"취소됨\n")


    def send_file(self) -> None:
        sock = self.active_socket()
        if not sock:
            self._append("연결이 없습니다.\n")
            return
        path = filedialog.askopenfilename(title="전송할 파일 선택")
        if not path:
            return
        send_packet(sock, b"<file>")
        send_packet(sock, str(str(path).split("/")[-1]).encode("utf-8") )
        send_packet(sock, Path(path).read_bytes())
        self._append(f"파일 전송: {path}\n")

    def stop(self) -> None:
        self.running = False
        for sock in (self.connection, self.client_socket, self.server_socket):
            try:
                if sock:
                    sock.close()
            except OSError:
                pass
        self.connection = None
        self.client_socket = None
        self.server_socket = None

    def _append(self, text: str) -> None:
        self.after(0, lambda: (self.log.insert("end", text), self.log.see("end")))

    @staticmethod
    def local_ip() -> str:
        try:
            # UDP 소켓의 임시 연결을 이용해 운영체제가 선택한 로컬 주소를 확인한다.
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect(("8.8.8.8", 80))
                return sock.getsockname()[0]
        except OSError:
            # 주소 확인에 실패하면 같은 컴퓨터 안에서 사용할 loopback 주소를 기본값으로 쓴다.
            return "127.0.0.1"


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return LanRemoteTool(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("network.lan_remote", "Same-WiFi LAN 통합", "네트워크", build, 20))
