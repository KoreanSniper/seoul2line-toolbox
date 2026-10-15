from __future__ import annotations

import tkinter as tk
from typing import Callable


def rounded_rect(canvas: tk.Canvas, x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> int:
    points = [
        x1 + radius, y1,
        x2 - radius, y1,
        x2, y1,
        x2, y1 + radius,
        x2, y2 - radius,
        x2, y2,
        x2 - radius, y2,
        x1 + radius, y2,
        x1, y2,
        x1, y2 - radius,
        x1, y1 + radius,
        x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=16, **kwargs)


class RoundedFrame(tk.Frame):
    def __init__(
        self,
        parent: tk.Widget,
        colors: dict[str, str],
        fill: str,
        border: str | None = None,
        radius: int = 14,
        padding: int = 14,
    ) -> None:
        super().__init__(parent, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.colors = colors
        self.fill = fill
        self.border = border or fill
        self.radius = radius
        self.padding = padding
        self.canvas = tk.Canvas(self, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=fill)
        self.window = self.canvas.create_window(padding, padding, window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", self._redraw)
        self.body.bind("<Configure>", self._fit_to_body)

    def _fit_to_body(self, _event: tk.Event) -> None:
        self.canvas.configure(
            width=max(self.body.winfo_reqwidth() + self.padding * 2, 40),
            height=max(self.body.winfo_reqheight() + self.padding * 2, 40),
        )

    def _redraw(self, event: tk.Event) -> None:
        self.canvas.delete("shape")
        width = max(event.width - 1, 1)
        height = max(event.height - 1, 1)
        rounded_rect(
            self.canvas,
            1,
            1,
            width,
            height,
            self.radius,
            fill=self.fill,
            outline=self.border,
            tags="shape",
        )
        self.canvas.tag_lower("shape")
        self.canvas.itemconfigure(
            self.window,
            width=max(event.width - self.padding * 2, 1),
            height=max(event.height - self.padding * 2, 1),
        )


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent: tk.Widget,
        text: str,
        command: Callable[[], object],
        colors: dict[str, str],
        accent: bool = False,
        compact: bool = False,
        radius: int = 11,
        anchor: str = "w",
        height: int | None = None,
    ) -> None:
        self.colors = colors
        self.command = command
        self.text = text
        self.accent = accent
        self.active = False
        self.radius = radius
        self.text_anchor = anchor
        self.pad_x = 12 if compact else 16
        self.height = height or (34 if compact else 40)
        super().__init__(
            parent,
            height=self.height,
            bg=parent.cget("bg"),
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.bind("<Configure>", lambda _event: self._draw())
        self.bind("<Button-1>", lambda _event: self.command())
        self.bind("<Enter>", lambda _event: self._draw(hover=True))
        self.bind("<Leave>", lambda _event: self._draw())
        self._draw()

    def set_active(self, active: bool) -> None:
        self.active = active
        self._draw()

    def _draw(self, hover: bool = False) -> None:
        self.delete("all")
        width = max(self.winfo_width(), 80)
        if self.accent:
            fill = self.colors["accent"]
            fg = self.colors["accent_text"]
        elif self.active:
            fill = self.colors["accent_soft"]
            fg = self.colors["accent"]
        else:
            fill = self.colors["surface_hover"] if hover else self.colors["field"]
            fg = self.colors["text"]
        rounded_rect(self, 1, 1, width - 1, self.height - 1, self.radius, fill=fill, outline=self.colors["border"])
        text_x = width // 2 if self.text_anchor == "center" else self.pad_x
        self.create_text(
            text_x,
            self.height // 2,
            text=self.text,
            anchor="center" if self.text_anchor == "center" else "w",
            fill=fg,
            font=("Segoe UI", 9, "bold"),
        )


def flat_button(
    parent: tk.Widget,
    text: str,
    command: Callable[[], object],
    colors: dict[str, str],
    accent: bool = False,
    compact: bool = False,
    anchor: str = "center",
) -> tk.Button:
    return tk.Button(
        parent,
        text=text,
        command=command,
        anchor=anchor,
        relief="flat",
        bd=0,
        padx=10 if compact else 14,
        pady=7 if compact else 10,
        bg=colors["accent"] if accent else colors["surface_hover"],
        fg=colors["accent_text"] if accent else colors["text"],
        activebackground=colors["accent"] if accent else colors["accent_soft"],
        activeforeground=colors["accent_text"] if accent else colors["text"],
        font=("Segoe UI", 9, "bold"),
        cursor="hand2",
    )


def styled_scrollbar(parent: tk.Widget, orient: str, command, colors: dict[str, str]) -> tk.Scrollbar:
    return tk.Scrollbar(
        parent,
        orient=orient,
        command=command,
        bg=colors["panel"],
        troughcolor=colors["surface"],
        activebackground=colors["accent"],
        highlightthickness=0,
        bd=0,
        relief="flat",
    )
