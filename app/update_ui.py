from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox
import webbrowser

from app.config import APP_DIR
from app.update_service import check_latest, download_release, launch_installer
from app.version import VERSION


class UpdateController:
    def __init__(self, app) -> None:
        self.app = app
        self.status = tk.StringVar(master=app, value=f"현재 버전 {VERSION}")
        self.events = queue.Queue()
        self.busy = False
        self.closed = False
        self.poll_job = app.after(150, self.poll)
        self.auto_job = app.after(3000, self.auto_check) if getattr(sys, "frozen", False) else None

    def auto_check(self) -> None:
        if self.app.config_store.get("updates", "automatic", default=True):
            self.check(manual=False)
        self.auto_job = self.app.after(6 * 60 * 60 * 1000, self.auto_check)

    def check(self, manual=True) -> None:
        if self.busy or self.closed:
            return
        self.busy = True
        self.status.set("업데이트 확인 중…")
        def worker():
            try:
                self.events.put(("checked", check_latest(), manual))
            except Exception as exc:
                self.events.put(("error", str(exc), manual))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self) -> None:
        if self.closed:
            return
        while True:
            try:
                kind, value, manual = self.events.get_nowait()
            except queue.Empty:
                break
            self.busy = False
            if kind == "error":
                self.status.set(f"업데이트 실패: {value}")
                if manual:
                    messagebox.showerror("업데이트 실패", value, parent=self.app)
            elif kind == "checked":
                if value is None:
                    self.status.set(f"현재 버전 {VERSION} · 새 업데이트 없음")
                    if manual:
                        messagebox.showinfo("업데이트", "새로운 정식 릴리스가 없습니다.", parent=self.app)
                elif not getattr(sys, "frozen", False):
                    self.status.set(f"설치본 {value.version} 사용 가능")
                    if messagebox.askyesno("업데이트", f"버전 {value.version} 설치본이 있습니다.\n소스 실행 중에는 설치본을 자동 교체하지 않습니다.\n다운로드 페이지를 여시겠습니까?", parent=self.app):
                        webbrowser.open(value.page_url)
                else:
                    self.status.set(f"버전 {value.version} 사용 가능")
                    if messagebox.askyesno("업데이트 설치", f"새 버전 {value.version}을 다운로드하고 설치하시겠습니까?\n\n설치 전에 작업을 저장하세요. 다운로드가 완료되면 앱이 종료되고 업데이트 후 다시 실행됩니다.\n사용자 설정과 저장 파일은 유지됩니다.", parent=self.app):
                        self.download(value)
            elif kind == "downloaded":
                installer, release = value
                try:
                    launch_installer(installer, release, APP_DIR / "updates")
                except (OSError, ValueError) as exc:
                    self.status.set(f"설치 시작 실패: {exc}")
                    messagebox.showerror("업데이트 실패", str(exc), parent=self.app)
                else:
                    self.app._close_app()
                    return
        self.poll_job = self.app.after(150, self.poll)

    def download(self, release) -> None:
        self.busy = True
        self.status.set("설치 파일 다운로드·검증 중…")
        def worker():
            try:
                path = download_release(release, APP_DIR / "updates")
                self.events.put(("downloaded", (path, release), True))
            except Exception as exc:
                self.events.put(("error", str(exc), True))
        threading.Thread(target=worker, daemon=True).start()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        for job in (self.poll_job, self.auto_job):
            if job is not None:
                self.app.after_cancel(job)
