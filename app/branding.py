from pathlib import Path
import sys
import tkinter as tk

from PIL import Image, ImageOps, ImageTk


ASSET_DIR = Path(__file__).resolve().parent / 'assets'
LOGO_PATH = ASSET_DIR / 'toolbox-logo.png'
ICON_PATH = ASSET_DIR / 'toolbox.ico'


def configure_app_id():
    if sys.platform == 'win32':
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('seoul2line.Toolbox')


def logo_image(master, size=40):
    with Image.open(LOGO_PATH) as image:
        scaled = ImageOps.pad(image.convert('RGBA'), (size, size),
                              method=Image.Resampling.LANCZOS, color='#000000')
    return ImageTk.PhotoImage(scaled, master=master)


def apply_window_icon(window):
    window._brand_icons = [logo_image(window, size) for size in (32, 64, 128)]
    window.iconphoto(True, *window._brand_icons)
    try:
        window.iconbitmap(default=str(ICON_PATH))
    except tk.TclError:
        pass  # iconphoto also supports platforms without Windows ICO handling.
