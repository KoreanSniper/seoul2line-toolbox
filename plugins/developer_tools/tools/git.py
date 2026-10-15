from __future__ import annotations

import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, styled_scrollbar
from app.palette import palette


class GitTool(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.colors = palette(app.dark_mode)
        self.repo = tk.StringVar(value=str(Path.cwd()))
        self.branch = tk.StringVar(value="-")
        self.remote = tk.StringVar(value="-")
        self.changed = tk.StringVar(value="0")
        self.status = tk.StringVar(value="Git 도구 대기 중")
        self._build()
        self.refresh_summary()

    def _build(self) -> None:
        colors = self.colors
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="Git / GitHub", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="상태 확인, add, commit, pull, push, GitHub 열기를 한 곳에서 처리합니다.", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 10)).grid(row=1, column=0, sticky="w", pady=(3, 0))
        RoundedButton(header, "상태 갱신", self.refresh_summary, colors, accent=True, compact=True, radius=10, anchor="center").grid(row=0, column=1, rowspan=2, sticky="e")

        path_bar = RoundedFrame(self, colors, colors["panel_soft"], colors["border"], radius=18, padding=12)
        path_bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        path_bar.body.columnconfigure(1, weight=1)
        tk.Label(path_bar.body, text="저장소", fg=colors["muted"], bg=colors["panel_soft"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        styled_entry(path_bar.body, colors, self.repo).grid(row=0, column=1, sticky="ew", ipady=8)
        RoundedButton(path_bar.body, "찾기", self.browse, colors, compact=True, radius=10, anchor="center", height=36).grid(row=0, column=2, padx=(8, 0))
        RoundedButton(path_bar.body, "적용", self.refresh_summary, colors, compact=True, radius=10, anchor="center", height=36).grid(row=0, column=3, padx=(8, 0))

        main = tk.Frame(self, bg=colors["panel"])
        main.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 12))
        main.columnconfigure(0, weight=2)
        main.columnconfigure(1, weight=3)
        main.rowconfigure(0, weight=1)

        left = RoundedFrame(main, colors, colors["surface"], colors["border"], radius=18, padding=14)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        tk.Label(left.body, text="저장소 요약", fg=colors["text"], bg=colors["surface"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(left.body, text="짧은 Git 명령으로 현재 상태를 읽습니다.", fg=colors["muted"], bg=colors["surface"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 10))
        summary_grid = tk.Frame(left.body, bg=colors["surface"])
        summary_grid.pack(fill="x")
        metric(summary_grid, colors, "브랜치", self.branch, 0, 0)
        metric(summary_grid, colors, "변경", self.changed, 0, 1)
        metric(summary_grid, colors, "원격", self.remote, 1, 0, span=2)

        tk.Label(left.body, text="원클릭 작업", fg=colors["accent"], bg=colors["surface"], font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(16, 8))
        for label, command, accent in (
            ("상태 보기", lambda: self.run_git(["status", "--short"]), False),
            ("Pull", lambda: self.run_git(["pull"]), False),
            ("전체 추가", lambda: self.run_git(["add", "."]), False),
            ("커밋", self.commit, True),
            ("Push", lambda: self.run_git(["push"]), False),
            ("GitHub 열기", self.open_github, True),
        ):
            RoundedButton(left.body, label, command, colors, accent=accent, compact=True, radius=10, anchor="center", height=36).pack(fill="x", pady=(0, 7))

        right = RoundedFrame(main, colors, colors["panel_soft"], colors["border"], radius=18, padding=14)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.body.columnconfigure(0, weight=1)
        right.body.rowconfigure(1, weight=1)
        tk.Label(right.body, text="출력", fg=colors["text"], bg=colors["panel_soft"], font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        output_wrap = tk.Frame(right.body, bg=colors["panel_soft"])
        output_wrap.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        output_wrap.columnconfigure(0, weight=1)
        output_wrap.rowconfigure(0, weight=1)
        self.output = tk.Text(
            output_wrap,
            bg=colors["field"],
            fg=colors["text"],
            insertbackground=colors["accent"],
            selectbackground=colors["accent_soft"],
            wrap="word",
            bd=0,
            relief="flat",
            padx=12,
            pady=12,
            font=("Consolas", 10),
        )
        scrollbar = styled_scrollbar(output_wrap, "vertical", self.output.yview, colors)
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        tk.Label(self, textvariable=self.status, fg=colors["muted"], bg=colors["panel"], anchor="w", font=("Segoe UI", 9)).grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 14))

    def browse(self) -> None:
        directory = filedialog.askdirectory()
        if directory:
            self.repo.set(directory)
            self.refresh_summary()

    def refresh_summary(self) -> None:
        if not self.is_repo():
            self.branch.set("-")
            self.remote.set("-")
            self.changed.set("0")
            self.write("Git 저장소가 아닙니다. 저장소 폴더를 선택하세요.")
            self.status.set("저장소 확인 필요")
            return
        self.branch.set(self.git_text(["branch", "--show-current"]) or "detached")
        remote = self.git_text(["remote", "get-url", "origin"]) or "-"
        self.remote.set(short_remote(remote))
        changed_lines = self.git_text(["status", "--short"]).splitlines()
        self.changed.set(str(len(changed_lines)))
        recent = self.git_text(["log", "--oneline", "-5"])
        status = self.git_text(["status", "--short"]) or "변경 없음"
        self.write(f"[최근 커밋]\n{recent or '커밋 없음'}\n\n[변경 상태]\n{status}")
        self.status.set("저장소 상태 갱신 완료")

    def refresh_metrics(self) -> None:
        if not self.is_repo():
            self.branch.set("-")
            self.remote.set("-")
            self.changed.set("0")
            return
        self.branch.set(self.git_text(["branch", "--show-current"]) or "detached")
        self.remote.set(short_remote(self.git_text(["remote", "get-url", "origin"]) or "-"))
        self.changed.set(str(len(self.git_text(["status", "--short"]).splitlines())))

    def is_repo(self) -> bool:
        result = self.run(["rev-parse", "--is-inside-work-tree"], timeout=10)
        return result.returncode == 0 and result.stdout.strip() == "true"

    def git_text(self, args: list[str]) -> str:
        result = self.run(args, timeout=15)
        return (result.stdout or result.stderr).strip()

    def run_git(self, args: list[str]) -> None:
        if not self.is_repo():
            self.refresh_summary()
            return
        result = self.run(args, timeout=60)
        self.write((result.stdout + result.stderr).strip() or "완료했습니다.")
        self.status.set(f"git {' '.join(args)} 완료" if result.returncode == 0 else f"git {' '.join(args)} 실패")
        self.refresh_metrics()

    def run(self, args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                ["git", *args],
                cwd=self.repo.get(),
                text=True,
                capture_output=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess(["git", *args], 1, "", str(exc))

    def commit(self) -> None:
        message = simpledialog.askstring("커밋", "커밋 메시지:")
        if message:
            self.run_git(["commit", "-m", message])

    def open_github(self) -> None:
        remote = self.git_text(["remote", "get-url", "origin"])
        url = github_url(remote)
        if not url:
            self.write("GitHub 원격 저장소를 찾지 못했습니다.")
            self.status.set("GitHub 원격 없음")
            return
        import webbrowser

        webbrowser.open(url)
        self.status.set("GitHub 저장소 열기 요청")

    def write(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text or "완료했습니다.")
        self.output.configure(state="disabled")


def styled_entry(parent: tk.Widget, colors: dict[str, str], variable: tk.StringVar) -> tk.Entry:
    return tk.Entry(
        parent,
        textvariable=variable,
        bg=colors["field"],
        fg=colors["text"],
        insertbackground=colors["accent"],
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=colors["border"],
        highlightcolor=colors["accent"],
        font=("Segoe UI", 10),
    )


def metric(parent: tk.Widget, colors: dict[str, str], label: str, value: tk.StringVar, row: int, column: int, span: int = 1) -> None:
    box = tk.Frame(parent, bg=colors["panel_soft"], highlightthickness=1, highlightbackground=colors["border"])
    box.grid(row=row, column=column, columnspan=span, sticky="ew", padx=(0, 8), pady=(0, 8))
    parent.columnconfigure(column, weight=1)
    tk.Label(box, text=label, fg=colors["muted"], bg=colors["panel_soft"], font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=10, pady=(8, 0))
    tk.Label(box, textvariable=value, fg=colors["text"], bg=colors["panel_soft"], font=("Consolas", 11, "bold"), anchor="w").pack(fill="x", padx=10, pady=(2, 8))


def short_remote(remote: str) -> str:
    if remote.startswith("git@github.com:"):
        return remote.removeprefix("git@github.com:").removesuffix(".git")
    if "github.com/" in remote:
        return remote.split("github.com/", 1)[1].removesuffix(".git")
    return remote


def github_url(remote: str) -> str:
    if remote.startswith("git@github.com:"):
        return "https://github.com/" + remote.removeprefix("git@github.com:").removesuffix(".git")
    if remote.startswith("https://github.com/"):
        return remote.removesuffix(".git")
    if remote.startswith("http://github.com/"):
        return remote.replace("http://", "https://", 1).removesuffix(".git")
    return ""


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return GitTool(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("developer.git", "Git / GitHub", "개발자", build, 20))

