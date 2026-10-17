from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
import webbrowser

from app.config import APP_DIR
from app.update_service import check_latest, check_previous, previous_versions, download_release, launch_installer
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
            elif kind == "versions":
                self.status.set(f"현재 버전 {VERSION}")
                self.show_previous_versions(value)
            elif kind == "previous":
                if getattr(sys, "frozen", False):
                    self.download(value)
                else:
                    self.status.set(f"이전 버전 {value.version} 다운로드 페이지")
                    webbrowser.open(value.page_url)
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

    def load_previous_versions(self) -> None:
        if self.busy or self.closed:
            return
        self.busy = True
        self.status.set("이전 버전 목록 확인 중…")
        def worker():
            try:
                self.events.put(("versions", previous_versions(), True))
            except Exception as exc:
                self.events.put(("error", str(exc), True))
        threading.Thread(target=worker, daemon=True).start()

    def show_previous_versions(self, versions) -> None:
        if not versions:
            messagebox.showinfo("이전 버전", "설치 가능한 이전 정식 버전이 없습니다.", parent=self.app)
            return
        dialog = tk.Toplevel(self.app)
        dialog.title("이전 버전으로 다운그레이드")
        dialog.transient(self.app)
        dialog.resizable(False, False)
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"현재 버전 {VERSION} · 설치할 이전 버전").pack(anchor="w")
        selection = ttk.Combobox(body, values=versions, state="readonly", width=35)
        selection.current(0)
        selection.pack(fill="x", pady=12)
        ttk.Label(body, text="이전 버전에서는 설정·저장 파일이 호환되지 않아\n데이터가 사라지거나 손상될 수 있습니다.\n중요한 데이터는 먼저 별도로 백업하세요.\n자동 업데이트 확인이 켜져 있으면 최신 버전을 다시 안내합니다.").pack(anchor="w")
        ttk.Button(body, text="선택한 버전으로 다운그레이드…",
                   command=lambda: self.downgrade(selection.get(), dialog)).pack(fill="x", pady=(16, 6))
        ttk.Button(body, text="취소", command=dialog.destroy).pack(fill="x")

    def downgrade(self, version, dialog) -> None:
        if self.busy or self.closed:
            return
        if not messagebox.askyesno(
            "다운그레이드 경고",
            f"{VERSION} → {version} 버전으로 다운그레이드합니다.\n\n"
            "설정·게임 저장·자동화 기록 등 데이터가 사라지거나 손상될 수 있습니다.\n"
            "데이터 복구는 보장되지 않습니다. 중요한 파일은 먼저 백업하세요.\n\n"
            "설치본은 다운로드·검증 후 앱을 종료하고 이전 버전을 설치합니다.\n"
            "소스 실행 중에는 다운로드 페이지를 엽니다.\n\n계속하시겠습니까?",
            parent=dialog, icon="warning", default=messagebox.NO,
        ):
            return
        dialog.destroy()
        self.busy = True
        self.status.set(f"이전 버전 {version} 검증 중…")
        def worker():
            try:
                self.events.put(("previous", check_previous(version), True))
            except Exception as exc:
                self.events.put(("error", str(exc), True))
        threading.Thread(target=worker, daemon=True).start()

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
