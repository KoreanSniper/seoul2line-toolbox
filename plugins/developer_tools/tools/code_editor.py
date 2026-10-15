from __future__ import annotations

import keyword
import re
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from app.tool_registry import ToolSpec
from app.ui import RoundedButton, RoundedFrame, styled_scrollbar
from app.palette import palette

class CodeEditor(tk.Frame):
    def __init__(self, parent: tk.Widget, app: object) -> None:
        super().__init__(parent, bg=palette(app.dark_mode)["panel"])
        self.app = app
        self.colors = palette(app.dark_mode)
        self.current_path: Path | None = None
        self.dirty = False
        self._highlight_job: str | None = None
        self.path_text = tk.StringVar(value="새 파일")
        self.status_text = tk.StringVar(value="1줄, 1칸 | UTF-8 | 저장됨")
        self.find_text_value = tk.StringVar()
        self._build()

    def _build(self) -> None:
        colors = self.colors
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        header = tk.Frame(self, bg=colors["panel"])
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 12))
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="코드 편집기", font=("Segoe UI", 22, "bold"), fg=colors["text"], bg=colors["panel"]).grid(row=0, column=0, sticky="w")
        tk.Label(header, textvariable=self.path_text, fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 10), anchor="w").grid(row=1, column=0, sticky="ew", pady=(3, 0))

        bar = RoundedFrame(self, colors, colors["panel_soft"], colors["border"], radius=18, padding=10)
        bar.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 12))
        for text, command, accent in (
            ("열기", self.open_file, False),
            ("저장", self.save_file, True),
            ("다른 이름", self.save_as, False),
            ("찾기", self.find_text, False),
            ("줄 이동", self.goto_line, False),
            ("주석", self.toggle_comment, False),
            ("실행", self.run_file, True),
        ):
            RoundedButton(bar.body, text, command, colors, accent=accent, compact=True, radius=10, anchor="center", height=36).pack(side="left", padx=(0, 7))

        main = tk.Frame(self, bg=colors["panel"])
        main.grid(row=2, column=0, sticky="nsew", padx=18, pady=(0, 12))
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=3)
        main.rowconfigure(1, weight=1)

        editor_panel = RoundedFrame(main, colors, colors["surface"], colors["border"], radius=18, padding=0)
        editor_panel.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        editor_panel.body.columnconfigure(1, weight=1)
        editor_panel.body.rowconfigure(0, weight=1)

        self.lines = tk.Text(editor_panel.body, width=5, padx=8, takefocus=0, bd=0, bg=colors["field"], fg=colors["subtle"], font=("Consolas", 10), relief="flat")
        self.lines.grid(row=0, column=0, sticky="ns")
        self.text = tk.Text(
            editor_panel.body,
            undo=True,
            wrap="none",
            bd=0,
            bg=colors["surface"],
            fg=colors["text"],
            insertbackground=colors["accent"],
            selectbackground=colors["accent_soft"],
            padx=12,
            pady=10,
            font=("Consolas", 10),
            relief="flat",
        )
        self.text.grid(row=0, column=1, sticky="nsew")
        yscroll = styled_scrollbar(editor_panel.body, "vertical", self._yview, colors)
        xscroll = styled_scrollbar(editor_panel.body, "horizontal", self.text.xview, colors)
        self.text.configure(yscrollcommand=lambda first, last: self._on_text_scroll(first, last, yscroll), xscrollcommand=xscroll.set)
        yscroll.grid(row=0, column=2, sticky="ns")
        xscroll.grid(row=1, column=1, sticky="ew")

        output_panel = RoundedFrame(main, colors, colors["panel_soft"], colors["border"], radius=18, padding=12)
        output_panel.grid(row=1, column=0, sticky="nsew")
        output_panel.body.columnconfigure(0, weight=1)
        output_panel.body.rowconfigure(1, weight=1)
        tk.Label(output_panel.body, text="실행 결과", fg=colors["text"], bg=colors["panel_soft"], font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        self.output = tk.Text(output_panel.body, height=7, bg=colors["field"], fg=colors["text"], insertbackground=colors["accent"], wrap="word", bd=0, relief="flat", padx=10, pady=8, font=("Consolas", 9))
        out_scroll = styled_scrollbar(output_panel.body, "vertical", self.output.yview, colors)
        self.output.configure(yscrollcommand=out_scroll.set, state="disabled")
        self.output.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        out_scroll.grid(row=1, column=1, sticky="ns", pady=(8, 0))

        tk.Label(self, textvariable=self.status_text, anchor="w", fg=colors["muted"], bg=colors["panel"], font=("Segoe UI", 9)).grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 14))

        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<KeyRelease>", self._schedule_highlight)
        self.text.bind("<ButtonRelease-1>", self._update_status)
        self.text.bind("<Tab>", self._insert_spaces)
        self.text.bind("<Control-s>", lambda _event: self._shortcut(self.save_file))
        self.text.bind("<Control-o>", lambda _event: self._shortcut(self.open_file))
        self.text.bind("<Control-f>", lambda _event: self._shortcut(self.find_text))
        self.text.bind("<Control-slash>", lambda _event: self.toggle_comment())
        self.text.bind("<MouseWheel>", self._after_wheel)
        self.lines.bind("<MouseWheel>", self._wheel_text)
        self.text.tag_configure("keyword", foreground="#67d8ef")
        self.text.tag_configure("string", foreground="#a6e22e")
        self.text.tag_configure("comment", foreground="#7f8c8d")
        self.text.tag_configure("number", foreground="#ae81ff")
        self.text.tag_configure("match", background="#8a6f15", foreground="#ffffff")
        self._update_lines()
        self._update_status()

    def _yview(self, *args) -> None:
        self.text.yview(*args)
        self._sync_line_scroll()

    def _on_text_scroll(self, first: str, last: str, scrollbar: tk.Scrollbar) -> None:
        scrollbar.set(first, last)
        self.lines.yview_moveto(float(first))

    def _sync_line_scroll(self) -> None:
        first = self.text.yview()[0]
        self.lines.yview_moveto(first)

    def _after_wheel(self, _event=None) -> None:
        self.after_idle(self._sync_line_scroll)

    def _wheel_text(self, event: tk.Event) -> str:
        self.text.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self._sync_line_scroll()
        return "break"

    def _on_modified(self, _event=None) -> None:
        self.text.edit_modified(False)
        self.dirty = True
        self._update_lines()
        self._update_status()
        self._schedule_highlight()

    def _update_lines(self) -> None:
        line_count = int(self.text.index("end-1c").split(".")[0])
        self.lines.configure(state="normal")
        self.lines.delete("1.0", "end")
        self.lines.insert("1.0", "\n".join(str(i) for i in range(1, line_count + 1)))
        self.lines.configure(state="disabled")
        self._sync_line_scroll()

    def _insert_spaces(self, _event=None) -> str:
        self.text.insert("insert", "    ")
        return "break"

    def _shortcut(self, command) -> str:
        command()
        return "break"

    def _update_status(self, _event=None) -> None:
        row, col = self.text.index("insert").split(".")
        path = str(self.current_path) if self.current_path else "새 파일"
        state = "수정됨" if self.dirty else "저장됨"
        self.status_text.set(f"{row}줄, {int(col) + 1}칸 | UTF-8 | {state} | {path}")

    def _schedule_highlight(self, _event=None) -> None:
        if self._highlight_job:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(180, self._highlight_visible_python)

    def _highlight_visible_python(self) -> None:
        self._highlight_job = None
        suffix = self.current_path.suffix.lower() if self.current_path else ".py"
        for tag in ("keyword", "string", "comment", "number"):
            self.text.tag_remove(tag, "1.0", "end")
        if suffix not in {".py", ".pyw"}:
            return
        content = self.text.get("1.0", "end-1c")
        keyword_pattern = r"\b(" + "|".join(re.escape(word) for word in keyword.kwlist) + r")\b"
        patterns = {
            "comment": r"#[^\n]*",
            "string": r"('([^'\\]|\\.)*'|\"([^\"\\]|\\.)*\")",
            "number": r"\b\d+(\.\d+)?\b",
            "keyword": keyword_pattern,
        }
        for tag, pattern in patterns.items():
            for match in re.finditer(pattern, content):
                self.text.tag_add(tag, f"1.0+{match.start()}c", f"1.0+{match.end()}c")

    def open_file(self) -> None:
        filename = filedialog.askopenfilename()
        if not filename:
            return
        path = Path(filename)
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="cp949", errors="replace")
        except OSError as exc:
            messagebox.showerror("열기", str(exc))
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", content)
        self.current_path = path
        self.path_text.set(str(path))
        self.dirty = False
        self.text.edit_modified(False)
        self._update_lines()
        self._schedule_highlight()
        self._update_status()
        self.write_output("파일을 열었습니다.")

    def save_file(self, notify: bool = True) -> None:
        if self.current_path is None:
            self.save_as()
            return
        try:
            self.current_path.write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("저장", str(exc))
            return
        self.dirty = False
        self._update_status()
        if notify:
            self.write_output("저장했습니다.")

    def save_as(self) -> None:
        filename = filedialog.asksaveasfilename()
        if not filename:
            return
        self.current_path = Path(filename)
        self.path_text.set(str(self.current_path))
        self.save_file(notify=False)
        self.write_output("다른 이름으로 저장했습니다.")

    def find_text(self) -> None:
        needle = simpledialog.askstring("찾기", "찾을 텍스트:")
        if not needle:
            return
        self.text.tag_remove("match", "1.0", "end")
        start = "1.0"
        count = 0
        first = ""
        while True:
            pos = self.text.search(needle, start, stopindex="end")
            if not pos:
                break
            end = f"{pos}+{len(needle)}c"
            self.text.tag_add("match", pos, end)
            first = first or pos
            start = end
            count += 1
        if first:
            self.text.mark_set("insert", first)
            self.text.see(first)
        self.write_output(f"찾기 결과: {count}개")

    def goto_line(self) -> None:
        line = simpledialog.askinteger("줄 이동", "이동할 줄 번호:", minvalue=1)
        if line:
            self.text.mark_set("insert", f"{line}.0")
            self.text.see("insert")
            self._update_status()

    def toggle_comment(self) -> str:
        start = self.text.index("sel.first linestart") if self.text.tag_ranges("sel") else self.text.index("insert linestart")
        end = self.text.index("sel.last lineend") if self.text.tag_ranges("sel") else self.text.index("insert lineend")
        start_line = int(start.split(".")[0])
        end_line = int(end.split(".")[0])
        lines = [self.text.get(f"{line}.0", f"{line}.end") for line in range(start_line, end_line + 1)]
        should_uncomment = all(line.lstrip().startswith("#") or not line.strip() for line in lines)
        for line_no, line_text in enumerate(lines, start=start_line):
            if not line_text.strip():
                continue
            if should_uncomment:
                hash_index = line_text.find("#")
                self.text.delete(f"{line_no}.{hash_index}", f"{line_no}.{hash_index + 1}")
                if self.text.get(f"{line_no}.{hash_index}", f"{line_no}.{hash_index + 1}") == " ":
                    self.text.delete(f"{line_no}.{hash_index}", f"{line_no}.{hash_index + 1}")
            else:
                indent = len(line_text) - len(line_text.lstrip())
                self.text.insert(f"{line_no}.{indent}", "# ")
        self.dirty = True
        self._schedule_highlight()
        self._update_status()
        return "break"

    def run_file(self) -> None:
        self.save_file(notify=False)
        if not self.current_path:
            return
        if self.current_path.suffix.lower() not in {".py", ".pyw"}:
            messagebox.showinfo("실행", "이 가벼운 실행기는 Python 파일만 실행합니다.")
            return
        try:
            result = subprocess.run(
                ["py", str(self.current_path)],
                cwd=str(self.current_path.parent),
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self.write_output(str(exc))
            return
        self.write_output(result.stdout + result.stderr or "완료했습니다.")

    def write_output(self, text: str) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("1.0", text)
        self.output.configure(state="disabled")


def build(parent: tk.Widget, app: object) -> tk.Widget:
    return CodeEditor(parent, app)


def register(registry) -> None:
    registry.register(ToolSpec("developer.code_editor", "코드 편집기", "개발자", build, 10))

