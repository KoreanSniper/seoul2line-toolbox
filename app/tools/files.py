from __future__ import annotations

import shutil
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, styled_scrollbar
from app.palette import palette

class FileTool(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.workspace = tk.StringVar(value=app.config_store.get("files", "workspace", default="."))
        self.filter_text = tk.StringVar()
        self.status = tk.StringVar(value="대기 중")
        self.items: list[Path] = []
        self.filtered_items: list[Path] = []
        self.detail_name = tk.StringVar(value="선택된 항목 없음")
        self.detail_body = tk.StringVar(value="왼쪽 목록에서 파일이나 폴더를 선택하세요.")
        self._build()
        self.filter_text.trace_add("write", lambda *_args: self.apply_filter())
        self.refresh()
        self.bind_shortcuts()

    def _build(self) -> None:
        colors = palette(self.app.dark_mode)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="파일", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(header, text="정리, 생성, 이동, 삭제, 수정 작업을 키보드 중심으로 빠르게 처리합니다.", font=("Segoe UI", 10), fg=colors["muted"], bg=colors["panel"]).grid(row=1, column=0, sticky="w", pady=(3, 0))
        RoundedButton(header, "새로고침", self.refresh, colors, accent=True, compact=True, radius=10, anchor="center").grid(row=0, column=1, rowspan=2, sticky="e")

        path_bar = RoundedFrame(self, colors, colors["panel_soft"], colors["border"], radius=18, padding=12)
        path_bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        path_bar.body.columnconfigure(1, weight=1)
        tk.Label(path_bar.body, text="작업 폴더", fg=colors["muted"], bg=colors["panel_soft"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 10))
        self.path_entry = styled_entry(path_bar.body, colors, self.workspace)
        self.path_entry.grid(row=0, column=1, sticky="ew", ipady=8)
        RoundedButton(path_bar.body, "이동", self.go_to_workspace, colors, compact=True, radius=10, anchor="center", height=36).grid(row=0, column=2, sticky="e", padx=(8, 0))
        RoundedButton(path_bar.body, "찾기", self.browse, colors, compact=True, radius=10, anchor="center", height=36).grid(row=0, column=3, sticky="e", padx=(8, 0))

        main = tk.Frame(self, bg=colors["panel"])
        main.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 12))
        main.columnconfigure(0, weight=3)
        main.columnconfigure(1, weight=2)
        main.rowconfigure(0, weight=1)

        left = RoundedFrame(main, colors, colors["surface"], colors["border"], radius=18, padding=12)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.body.columnconfigure(0, weight=1)
        left.body.rowconfigure(2, weight=1)

        search_row = tk.Frame(left.body, bg=colors["surface"])
        search_row.grid(row=0, column=0, sticky="ew")
        search_row.columnconfigure(1, weight=1)
        tk.Label(search_row, text="검색", fg=colors["muted"], bg=colors["surface"], font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8))
        styled_entry(search_row, colors, self.filter_text).grid(row=0, column=1, sticky="ew", ipady=8)
        RoundedButton(search_row, "위로", self.go_parent, colors, compact=True, radius=10, anchor="center", height=36).grid(row=0, column=2, padx=(8, 0))

        actions = tk.Frame(left.body, bg=colors["surface"])
        actions.grid(row=1, column=0, sticky="ew", pady=(10, 8))
        for text, command in (
            ("파일", self.new_file),
            ("폴더", self.new_folder),
            ("열기", self.open_or_edit),
            ("이름", self.rename),
            ("이동", self.move),
            ("복제", self.duplicate),
            ("경로", self.copy_path),
            ("삭제", self.delete),
        ):
            RoundedButton(actions, text, command, colors, compact=True, radius=10, anchor="center", height=34).pack(side="left", fill="x", expand=True, padx=(0, 5))

        list_wrap = tk.Frame(left.body, bg=colors["surface"])
        list_wrap.grid(row=2, column=0, sticky="nsew")
        list_wrap.columnconfigure(0, weight=1)
        list_wrap.rowconfigure(0, weight=1)
        self.listbox = tk.Listbox(
            list_wrap,
            bg=colors["field"],
            fg=colors["text"],
            selectbackground=colors["accent_soft"],
            selectforeground=colors["accent"],
            activestyle="none",
            bd=0,
            highlightthickness=1,
            highlightbackground=colors["border"],
            font=("Consolas", 10),
            exportselection=False,
        )
        scrollbar = styled_scrollbar(list_wrap, "vertical", self.listbox.yview, colors)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        self.listbox.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.listbox.bind("<<ListboxSelect>>", lambda _event: self.update_details())
        self.listbox.bind("<Double-Button-1>", lambda _event: self.open_or_edit())

        right = RoundedFrame(main, colors, colors["panel_soft"], colors["border"], radius=18, padding=16)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.body.columnconfigure(0, weight=1)
        tk.Label(right.body, textvariable=self.detail_name, fg=colors["text"], bg=colors["panel_soft"], font=("Segoe UI", 14, "bold"), anchor="w").pack(fill="x")
        tk.Label(right.body, textvariable=self.detail_body, fg=colors["muted"], bg=colors["panel_soft"], font=("Consolas", 9), justify="left", anchor="nw").pack(fill="x", pady=(10, 16))
        quick = tk.Frame(right.body, bg=colors["panel_soft"])
        quick.pack(fill="x")
        for text, command in (("열기/수정", self.open_or_edit), ("경로 복사", self.copy_path), ("삭제", self.delete)):
            RoundedButton(quick, text, command, colors, compact=True, radius=10, anchor="center", height=36).pack(fill="x", pady=(0, 8))

        tk.Label(
            right.body,
            text="Ctrl+N 파일 | Ctrl+Shift+N 폴더 | Enter 열기 | F2 이름 변경\nCtrl+M 이동 | Ctrl+D 복제 | Ctrl+L 경로 복사 | Delete 삭제 | F5 새로고침",
            fg=colors["muted"],
            bg=colors["panel_soft"],
            justify="left",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(8, 0))

        tk.Label(self, textvariable=self.status, fg=colors["muted"], bg=colors["panel"], anchor="w", font=("Segoe UI", 9)).grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 14))

    def bind_shortcuts(self) -> None:
        hotkeys = self.app.config_store.get("hotkeys", default={})
        def safe_bind(sequence: str, callback) -> None:
            # 외부에서 config.json을 직접 고쳐도 잘못된 keysym이 앱 전체를 중단시키지 않습니다.
            try:
                self.bind_all(sequence, callback)
            except tk.TclError:
                return

        safe_bind(hotkeys.get("quick_new_file", "<Control-n>"), lambda _e: self.new_file())
        safe_bind(hotkeys.get("quick_delete", "<Delete>"), lambda _e: self.delete())
        safe_bind(hotkeys.get("quick_move", "<Control-m>"), lambda _e: self.move())
        safe_bind(hotkeys.get("quick_refresh", "<F5>"), lambda _e: self.refresh())
        self.bind_all("<Control-Shift-N>", lambda _e: self.new_folder())
        self.bind_all("<Return>", lambda _e: self.open_or_edit())
        self.bind_all("<F2>", lambda _e: self.rename())
        self.bind_all("<Control-d>", lambda _e: self.duplicate())
        self.bind_all("<Control-l>", lambda _e: self.copy_path())

    def browse(self) -> None:
        directory = filedialog.askdirectory()
        if directory:
            self.workspace.set(directory)
            self.save_workspace()
            self.refresh()

    def go_to_workspace(self) -> None:
        root = Path(self.workspace.get()).expanduser()
        if not root.exists() or not root.is_dir():
            messagebox.showwarning("파일", "존재하는 폴더 경로를 입력하세요.")
            return
        self.workspace.set(str(root))
        self.save_workspace()
        self.refresh()

    def go_parent(self) -> None:
        root = Path(self.workspace.get()).expanduser()
        parent = root.parent
        if parent != root:
            self.workspace.set(str(parent))
            self.save_workspace()
            self.refresh()

    def save_workspace(self) -> None:
        self.app.config_store.set("files", "workspace", value=self.workspace.get())

    def refresh(self) -> None:
        root = Path(self.workspace.get()).expanduser()
        self.items = []
        if not root.exists() or not root.is_dir():
            self.status.set("작업 폴더를 찾을 수 없습니다.")
            self.apply_filter()
            return
        try:
            self.items = sorted(root.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except OSError as exc:
            self.status.set(f"폴더를 읽을 수 없습니다: {exc}")
            self.items = []
        self.apply_filter()
        self.status.set(f"{root} | {len(self.filtered_items)}개 표시")

    def apply_filter(self) -> None:
        query = self.filter_text.get().strip().lower()
        self.filtered_items = [item for item in self.items if query in item.name.lower()]
        self.listbox.delete(0, "end")
        for item in self.filtered_items:
            icon = "DIR " if item.is_dir() else "FILE"
            self.listbox.insert("end", f"{icon}  {item.name}")
        self.update_details()

    def selected_path(self) -> Path | None:
        selection = self.listbox.curselection()
        if not selection:
            return None
        index = selection[0]
        if index >= len(self.filtered_items):
            return None
        return self.filtered_items[index]

    def update_details(self) -> None:
        path = self.selected_path()
        if not path:
            self.detail_name.set("선택된 항목 없음")
            self.detail_body.set("왼쪽 목록에서 파일이나 폴더를 선택하세요.")
            return
        try:
            stat = path.stat()
            modified = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            size = folder_size_label(path) if path.is_dir() else file_size_label(stat.st_size)
        except OSError:
            modified = "알 수 없음"
            size = "알 수 없음"
        self.detail_name.set(path.name)
        self.detail_body.set(
            f"종류: {'폴더' if path.is_dir() else '파일'}\n"
            f"크기: {size}\n"
            f"수정: {modified}\n"
            f"경로: {path}"
        )

    def new_file(self) -> None:
        name = simpledialog.askstring("파일 생성", "파일 이름:")
        if name:
            (Path(self.workspace.get()) / name).touch(exist_ok=True)
            self.refresh()

    def new_folder(self) -> None:
        name = simpledialog.askstring("폴더 생성", "폴더 이름:")
        if name:
            (Path(self.workspace.get()) / name).mkdir(exist_ok=True)
            self.refresh()

    def rename(self) -> None:
        path = self.selected_path()
        if not path:
            return
        name = simpledialog.askstring("이름 변경", "새 이름:", initialvalue=path.name)
        if name:
            path.rename(path.with_name(name))
            self.refresh()

    def move(self) -> None:
        path = self.selected_path()
        if not path:
            return
        target = filedialog.askdirectory()
        if target:
            shutil.move(str(path), str(Path(target) / path.name))
            self.refresh()

    def duplicate(self) -> None:
        path = self.selected_path()
        if not path:
            return
        new_name = simpledialog.askstring("복제", "복사본 이름:", initialvalue=f"{path.stem}_copy{path.suffix}")
        if not new_name:
            return
        target = path.with_name(new_name)
        if target.exists():
            messagebox.showwarning("복제", "같은 이름의 항목이 이미 있습니다.")
            return
        if path.is_dir():
            shutil.copytree(path, target)
        else:
            shutil.copy2(path, target)
        self.refresh()

    def copy_path(self) -> None:
        path = self.selected_path()
        if not path:
            return
        self.clipboard_clear()
        self.clipboard_append(str(path))
        self.status.set("경로를 클립보드에 복사했습니다.")

    def open_or_edit(self) -> None:
        path = self.selected_path()
        if not path:
            return
        if path.is_dir():
            self.workspace.set(str(path))
            self.save_workspace()
            self.refresh()
            return
        self.open_editor(path)

    def open_editor(self, path: Path) -> None:
        editor = tk.Toplevel(self)
        editor.title(path.name)
        editor.geometry("900x620")
        colors = palette(self.app.dark_mode)
        editor.configure(bg=colors["panel"])
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(0, weight=1)

        text = tk.Text(
            editor,
            bg=colors["field"],
            fg=colors["text"],
            insertbackground=colors["accent"],
            selectbackground=colors["accent_soft"],
            wrap="none",
            relief="flat",
            bd=0,
            padx=12,
            pady=12,
            font=("Consolas", 10),
        )
        yscroll = styled_scrollbar(editor, "vertical", text.yview, colors)
        xscroll = styled_scrollbar(editor, "horizontal", text.xview, colors)
        text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        text.grid(row=0, column=0, sticky="nsew", padx=(12, 0), pady=(12, 0))
        yscroll.grid(row=0, column=1, sticky="ns", pady=(12, 0), padx=(0, 12))
        xscroll.grid(row=1, column=0, sticky="ew", padx=(12, 0), pady=(0, 12))

        try:
            text.insert("1.0", path.read_text(encoding="utf-8"))
        except UnicodeDecodeError:
            text.insert("1.0", path.read_text(encoding="cp949", errors="replace"))
        except OSError as exc:
            text.insert("1.0", f"파일을 읽을 수 없습니다: {exc}")

        bottom = tk.Frame(editor, bg=colors["panel"])
        bottom.grid(row=2, column=0, columnspan=2, sticky="ew", padx=12, pady=(0, 12))
        bottom.columnconfigure(0, weight=1)
        tk.Label(bottom, text=str(path), fg=colors["muted"], bg=colors["panel"], anchor="w", font=("Segoe UI", 9)).grid(row=0, column=0, sticky="ew")

        def save() -> None:
            try:
                path.write_text(text.get("1.0", "end-1c"), encoding="utf-8")
            except OSError as exc:
                messagebox.showerror("파일", f"저장할 수 없습니다.\n{exc}")
                return
            self.status.set(f"{path.name} 저장 완료")
            self.refresh()

        RoundedButton(bottom, "저장", save, colors, accent=True, compact=True, radius=10, anchor="center").grid(row=0, column=1, sticky="e")

    def delete(self) -> None:
        path = self.selected_path()
        if not path:
            return
        if not messagebox.askyesno("삭제", f"{path.name} 항목을 삭제할까요?"):
            return
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        self.refresh()


def styled_entry(parent: tk.Widget, colors: dict[str, str], variable: tk.StringVar, placeholder: str | None = None) -> tk.Entry:
    entry = tk.Entry(
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
    if placeholder and not variable.get():
        entry.insert(0, placeholder)
        entry.configure(fg=colors["muted"])

        def focus_in(_event: tk.Event) -> None:
            if entry.get() == placeholder:
                entry.delete(0, "end")
                entry.configure(fg=colors["text"])

        def focus_out(_event: tk.Event) -> None:
            if not entry.get():
                entry.insert(0, placeholder)
                entry.configure(fg=colors["muted"])

        entry.bind("<FocusIn>", focus_in)
        entry.bind("<FocusOut>", focus_out)
    return entry


def file_size_label(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{size} B"


def folder_size_label(path: Path) -> str:
    try:
        count = sum(1 for _ in path.iterdir())
    except OSError:
        return "읽기 실패"
    return f"{count}개 항목"


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return FileTool(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("files.manager", "파일 관리자", "파일", build, 0))
