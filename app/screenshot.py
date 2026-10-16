from __future__ import annotations

import ctypes
import ctypes.wintypes
import io
import sys
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk

from PIL import Image, ImageGrab, ImageTk
from app.paths import data_directory


VK_SNAPSHOT = 0x2C
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
CF_DIB = 8
GMEM_MOVEABLE = 0x0002
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79


class ScreenshotHotkeyManager:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self._thread: threading.Thread | None = None
        self._thread_id = ctypes.wintypes.DWORD(0)
        self._hotkey_id = 1202
        self._running = threading.Event()
        self._overlay: RegionCaptureOverlay | None = None

    def start(self) -> None:
        if sys.platform != "win32" or self._thread is not None:
            return
        self._running.set()
        self._thread = threading.Thread(target=self._message_loop, name="PrintScreenHotkey", daemon=True)
        self._thread.start()
        self.root.bind_all("<Print>", lambda _event: self.capture_now())

    def stop(self) -> None:
        self._running.clear()
        user32 = ctypes.windll.user32
        if self._thread_id.value:
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)

    def capture_now(self) -> None:
        self.root.after(0, self._open_overlay)

    def _message_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = ctypes.wintypes.DWORD(kernel32.GetCurrentThreadId())
        registered = user32.RegisterHotKey(None, self._hotkey_id, MOD_NOREPEAT, VK_SNAPSHOT)
        if not registered:
            self._running.clear()
            return
        msg = ctypes.wintypes.MSG()
        try:
            while self._running.is_set() and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == WM_HOTKEY and msg.wParam == self._hotkey_id:
                    self.capture_now()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, self._hotkey_id)

    def _open_overlay(self) -> None:
        if self._overlay is not None and self._overlay.exists:
            self._overlay.lift()
            return
        self._overlay = RegionCaptureOverlay(self.root, self._on_capture_done)

    def _on_capture_done(self, image: Image.Image | None, path: Path | None) -> None:
        self._overlay = None
        if image is None or path is None:
            return
        try:
            copy_image_to_clipboard(image)
        except OSError:
            pass
        self._show_toast(f"캡쳐 완료\n{path.name}")

    def _show_toast(self, text: str) -> None:
        from app.palette import palette
        colors = palette(getattr(self.root, "dark_mode", True))
        bg = colors["panel"]
        fg = colors["text"]
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)
        toast.attributes("-topmost", True)
        toast.configure(bg=bg)
        toast.geometry(f"220x58+{self.root.winfo_screenwidth() - 250}+36")
        tk.Label(toast, text=text, bg=bg, fg=fg, justify="left", font=("Segoe UI", 9, "bold")).pack(fill="both", expand=True, padx=14, pady=10)
        toast.after(1400, toast.destroy)


class RegionCaptureOverlay:
    def __init__(self, root: tk.Tk, done_callback) -> None:
        self.root = root
        self.done_callback = done_callback
        self.exists = True
        self.start: tuple[int, int] | None = None
        self.rect_id: int | None = None
        self.dim_id: int | None = None
        self.path: Path | None = None

        self.bounds = virtual_screen_bounds()
        self.image = ImageGrab.grab(all_screens=True)
        self.window = tk.Toplevel(root)
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.98)
        self.window.configure(bg="black")
        self.window.geometry(format_geometry(*self.bounds))
        self.window.focus_force()

        width, height, _x, _y = self.bounds
        self.photo = ImageTk.PhotoImage(self.image)
        self.canvas = tk.Canvas(self.window, width=width, height=height, highlightthickness=0, bd=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        self.dim_id = self.canvas.create_rectangle(0, 0, width, height, fill="#000000", stipple="gray50", outline="")
        self.info_id = self.canvas.create_text(
            width // 2,
            32,
            text="드래그해서 캡쳐할 영역을 선택하세요. Esc 취소",
            fill="#ffffff",
            font=("Segoe UI", 13, "bold"),
        )
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.window.bind("<Escape>", lambda _event: self._finish(None, None))

    def lift(self) -> None:
        self.window.lift()
        self.window.focus_force()

    def _press(self, event: tk.Event) -> None:
        self.start = (clamp(event.x, 0, self.bounds[0]), clamp(event.y, 0, self.bounds[1]))
        if self.rect_id is not None:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(*self.start, *self.start, outline="#2dd4bf", width=2)

    def _drag(self, event: tk.Event) -> None:
        if self.start is None or self.rect_id is None:
            return
        x = clamp(event.x, 0, self.bounds[0])
        y = clamp(event.y, 0, self.bounds[1])
        self.canvas.coords(self.rect_id, self.start[0], self.start[1], x, y)

    def _release(self, event: tk.Event) -> None:
        if self.start is None:
            self._finish(None, None)
            return
        x1, y1 = self.start
        x2 = clamp(event.x, 0, self.bounds[0])
        y2 = clamp(event.y, 0, self.bounds[1])
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        if right - left < 3 or bottom - top < 3:
            self._finish(None, None)
            return
        image = self.image.crop((left, top, right, bottom))
        path = screenshot_dir() / f"capture_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        image.save(path)
        self._finish(image, path)

    def _finish(self, image: Image.Image | None, path: Path | None) -> None:
        self.exists = False
        try:
            self.window.destroy()
        finally:
            self.done_callback(image, path)


def virtual_screen_bounds() -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    width = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    height = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return width, height, x, y


def format_geometry(width: int, height: int, x: int, y: int) -> str:
    return f"{width}x{height}{x:+d}{y:+d}"


def screenshot_dir() -> Path:
    path = data_directory() / "screenshots"
    path.mkdir(parents=True, exist_ok=True)
    return path


def copy_image_to_clipboard(image: Image.Image) -> None:
    output = io.BytesIO()
    image.convert("RGB").save(output, "BMP")
    data = output.getvalue()[14:]
    output.close()

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.argtypes = (ctypes.c_uint, ctypes.c_size_t)
    kernel32.GlobalAlloc.restype = ctypes.wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = (ctypes.wintypes.HGLOBAL,)
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = (ctypes.wintypes.HGLOBAL,)
    kernel32.GlobalUnlock.restype = ctypes.wintypes.BOOL
    user32.SetClipboardData.argtypes = (ctypes.c_uint, ctypes.wintypes.HANDLE)
    user32.SetClipboardData.restype = ctypes.wintypes.HANDLE

    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise OSError("GlobalAlloc failed")
    pointer = kernel32.GlobalLock(handle)
    if not pointer:
        raise OSError("GlobalLock failed")
    ctypes.memmove(pointer, data, len(data))
    kernel32.GlobalUnlock(handle)

    if not user32.OpenClipboard(None):
        raise OSError("OpenClipboard failed")
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_DIB, handle):
            raise OSError("SetClipboardData failed")
    finally:
        user32.CloseClipboard()


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))
