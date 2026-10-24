"""HTTPS room protocol; no Tk calls or credentials persisted by this module."""
from __future__ import annotations

import http.client
import json
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit

MAX_FILE = 25 * 1024 * 1024


class TransferError(Exception):
    pass


class TransferClient:
    def __init__(self, endpoint: str, token: str, name: str = "나"):
        url = urlsplit(endpoint.strip())
        local = url.scheme == "http" and url.hostname in {"127.0.0.1", "localhost", "::1"}
        if (url.scheme != "https" and not local) or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
            raise TransferError("서버 주소는 HTTPS 주소여야 합니다. 로컬 개발만 HTTP를 허용합니다.")
        if not token.strip() or any(c in token for c in "\r\n"):
            raise TransferError("서버 인증 토큰을 입력하세요.")
        if not name.strip() or len(name.strip()) > 40:
            raise TransferError("표시 이름은 1~40자로 입력하세요.")
        self.url, self.token, self.name = url, token.strip(), name.strip()
        self.room = self.key = ""
        self.cursor = 0
        self.cancel = threading.Event()

    def _connection(self):
        cls = http.client.HTTPSConnection if self.url.scheme == "https" else http.client.HTTPConnection
        return cls(self.url.hostname, self.url.port, timeout=20)

    def _headers(self):
        return {"Authorization": f"Bearer {self.token}", "X-Room-Key": self.key}

    @staticmethod
    def _check(response):
        if not 200 <= response.status < 300:
            raw = response.read(16384)
            try:
                message = json.loads(raw).get("error", "서버 요청 실패")
            except (ValueError, AttributeError):
                message = f"서버 요청 실패 (HTTP {response.status})"
            raise TransferError(str(message))

    def request(self, method, path, data=None):
        if self.cancel.is_set():
            raise TransferError("연결이 해제되었습니다.")
        conn = self._connection()
        try:
            headers = self._headers()
            headers["Content-Type"] = "application/json"
            conn.request(method, path, body=json.dumps(data, ensure_ascii=False).encode() if data is not None else None, headers=headers)
            response = conn.getresponse()
            self._check(response)
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise TransferError("서버 응답이 너무 큽니다.")
            return json.loads(raw)
        finally:
            conn.close()

    @property
    def invitation(self):
        return f"{self.room}:{self.key}"

    def create(self):
        result = self.request("POST", "/rooms", {})
        self._set_room(f"{result['id']}:{result['key']}")
        return self.join(self.invitation)

    def _set_room(self, invitation):
        if not re.fullmatch(r"[a-f0-9]{32}:[a-f0-9]{64}", invitation.strip()):
            raise TransferError("복사한 전체 방 코드를 입력하세요.")
        self.room, self.key = invitation.strip().split(":")
        self.cursor = 0

    def join(self, invitation):
        self._set_room(invitation)
        start = time.monotonic()
        result = self.request("POST", f"/rooms/{self.room}/join", {})
        result["latency"] = round((time.monotonic() - start) * 1000)
        return result

    def events(self):
        result = self.request("GET", f"/rooms/{self.room}/events?after={self.cursor}")
        events = result["events"]
        if events:
            self.cursor = max(event["id"] for event in events)
        return events

    def send(self, text):
        if not text.strip() or len(text) > 4000:
            raise TransferError("메시지는 1~4,000자로 입력하세요.")
        self.request("POST", f"/rooms/{self.room}/events", {"text": text, "name": self.name})

    def upload(self, path: Path, progress):
        size = path.stat().st_size
        if not 0 < size <= MAX_FILE:
            raise TransferError("파일은 1바이트~25 MiB까지 전송할 수 있습니다.")
        if len(path.name) > 240:
            raise TransferError("파일 이름은 240자까지 지원합니다.")
        conn = self._connection()
        try:
            conn.putrequest("PUT", f"/rooms/{self.room}/files/{uuid.uuid4()}")
            for key, value in {**self._headers(), "Content-Length": str(size), "Content-Type": "application/octet-stream", "X-File-Name": quote(path.name)}.items():
                conn.putheader(key, value)
            conn.endheaders()
            sent = 0
            with path.open("rb") as source:
                while sent < size:
                    if self.cancel.is_set():
                        raise TransferError("전송이 취소되었습니다.")
                    chunk = source.read(min(65536, size - sent))
                    if not chunk:
                        raise TransferError("전송 중 원본 파일 크기가 변경되었습니다.")
                    conn.send(chunk)
                    sent += len(chunk)
                    progress(sent, size)
            response = conn.getresponse()
            self._check(response)
            response.read(16384)
        finally:
            conn.close()

    def download(self, file_id: str, destination: Path, expected_size: int, progress):
        if not re.fullmatch(r"[a-f0-9-]{36}", file_id) or not 0 < expected_size <= MAX_FILE:
            raise TransferError("파일 정보가 올바르지 않습니다.")
        # Exclusive temporary file beside the destination; failed transfers never replace it.
        temp = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
        conn = self._connection()
        try:
            conn.request("GET", f"/rooms/{self.room}/files/{file_id}", headers=self._headers())
            response = conn.getresponse()
            self._check(response)
            received = 0
            with temp.open("xb") as output:
                while True:
                    if self.cancel.is_set():
                        raise TransferError("전송이 취소되었습니다.")
                    chunk = response.read(min(65536, expected_size - received + 1))
                    if not chunk:
                        break
                    received += len(chunk)
                    if received > expected_size:
                        raise TransferError("파일 크기가 일치하지 않습니다.")
                    output.write(chunk)
                    progress(received, expected_size)
            if received != expected_size:
                raise TransferError("다운로드가 중단되었습니다. 다시 시도하세요.")
            temp.replace(destination)
        finally:
            conn.close()
            temp.unlink(missing_ok=True)
