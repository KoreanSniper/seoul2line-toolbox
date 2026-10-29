import tkinter as tk

from app.tools.voice_fx_editor import VoiceFXEditor
from app.ui import RoundedButton, styled_scrollbar


class SoundboardFXDialog(tk.Toplevel):
    def __init__(self, parent, colors, items, apply, cancel):
        super().__init__(parent, bg=colors["panel"])
        self.title("사운드보드 · 목소리 변조 복사")
        self.geometry("660x760")
        self.minsize(480, 540)
        self.transient(parent.winfo_toplevel())
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        self.status = tk.StringVar(value="여러 사운드를 선택할 수 있습니다. 원본은 유지하고 새 항목으로 등록합니다.")
        tk.Label(self, textvariable=self.status, bg=colors["panel"], fg=colors["text"], wraplength=450, justify="left").grid(row=0, column=0, sticky="ew", padx=12, pady=8)
        wrap = tk.Frame(self, bg=colors["panel"])
        wrap.grid(row=1, column=0, sticky="ew", padx=12)
        wrap.columnconfigure(0, weight=1)
        self.items = [i for i in items if i["path"]]
        self.selection = tk.Listbox(wrap, selectmode="extended", exportselection=False, height=4,
            bg=colors["field"], fg=colors["text"], selectbackground=colors["accent"], selectforeground=colors["accent_text"])
        self.selection.grid(row=0, column=0, sticky="ew")
        bar = styled_scrollbar(wrap, "vertical", self.selection.yview, colors)
        bar.grid(row=0, column=1, sticky="ns")
        self.selection.configure(yscrollcommand=bar.set)
        for item in self.items:
            self.selection.insert("end", item["title"])
        self.fx = VoiceFXEditor(self, colors, self.status)
        self.fx.grid(row=2, column=0, sticky="nsew", padx=12, pady=8)
        actions = tk.Frame(self, bg=colors["panel"])
        actions.grid(row=3, column=0, sticky="ew", padx=12, pady=10)
        for index, (text, action) in enumerate((("선택 항목 변조 복사", lambda: apply([self.items[i]["id"] for i in self.selection.curselection()], self.fx.snapshot())),
                                                ("취소 / 닫기", self.destroy))):
            actions.columnconfigure(index, weight=1)
            button = RoundedButton(actions, text, action, colors, compact=True)
            button.configure(width=190)
            button.grid(row=0, column=index, sticky="ew", padx=4)
        self.cancel_callback = cancel
        self.protocol("WM_DELETE_WINDOW", self.destroy)

    def destroy(self):
        if not self.winfo_exists():
            return
        self.cancel_callback()
        super().destroy()
        self.status = None
