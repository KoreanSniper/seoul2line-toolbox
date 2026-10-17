"""Foreground-only Windows raw mouse input; no keyboard/global hooks."""
import ctypes as C
from ctypes import wintypes as W


class Device(C.Structure):
    _fields_ = [("page", W.USHORT), ("usage", W.USHORT), ("flags", W.DWORD), ("window", W.HWND)]


class Header(C.Structure):
    _fields_ = [("kind", W.DWORD), ("size", W.DWORD), ("device", W.HANDLE), ("param", W.WPARAM)]


class Mouse(C.Structure):
    _fields_ = [("flags", W.USHORT), ("buttons", W.ULONG), ("raw_buttons", W.ULONG),
                ("x", W.LONG), ("y", W.LONG), ("extra", W.ULONG)]


class Packet(C.Structure):
    _fields_ = [("header", Header), ("mouse", Mouse)]


class RawMouse:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.dx = self.dy = 0
        self.error = None
        self.old_proc = None
        self.closed = False
        self.user = C.WinDLL("user32", use_last_error=True)
        self.user.RegisterRawInputDevices.argtypes = [C.POINTER(Device), W.UINT, W.UINT]
        self.user.RegisterRawInputDevices.restype = W.BOOL
        self.user.GetRawInputData.argtypes = [W.HANDLE, W.UINT, W.LPVOID, C.POINTER(W.UINT), W.UINT]
        self.user.GetRawInputData.restype = W.UINT
        self.set_proc = self.user.SetWindowLongPtrW if C.sizeof(C.c_void_p) == 8 else self.user.SetWindowLongW
        self.set_proc.argtypes = [W.HWND, C.c_int, C.c_ssize_t]
        self.set_proc.restype = C.c_ssize_t
        self.user.CallWindowProcW.argtypes = [C.c_void_p, W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        self.user.CallWindowProcW.restype = C.c_ssize_t
        self.user.ClipCursor.argtypes = [C.POINTER(W.RECT)]
        self.user.ClipCursor.restype = W.BOOL
        self.user.GetClipCursor.argtypes = [C.POINTER(W.RECT)]
        self.user.GetClipCursor.restype = W.BOOL
        self.clip = None
        proc_type = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        self.callback = proc_type(self._receive)
        C.set_last_error(0)
        self.old_proc = self.set_proc(hwnd, -4, C.cast(self.callback, C.c_void_p).value)
        if not self.old_proc:
            raise C.WinError(C.get_last_error())
        if not self.user.RegisterRawInputDevices(C.byref(Device(1, 2, 0, hwnd)), 1, C.sizeof(Device)):
            self.set_proc(hwnd, -4, self.old_proc)
            self.old_proc = None
            raise C.WinError(C.get_last_error())

    def _receive(self, hwnd, message, param, handle):
        if message == 0x00FF and not self.closed:
            try:
                packet, size = Packet(), W.UINT(C.sizeof(Packet))
                count = self.user.GetRawInputData(handle, 0x10000003, C.byref(packet), C.byref(size), C.sizeof(Header))
                if count == 0xFFFFFFFF:
                    raise C.WinError(C.get_last_error())
                if count >= C.sizeof(Packet) and packet.header.kind == 0:
                    if packet.mouse.flags & 1:
                        self.error = "상대 이동을 지원하는 마우스가 필요합니다."
                    else:
                        self.dx += packet.mouse.x
                        self.dy += packet.mouse.y
            except Exception as exc:
                self.error = str(exc)
        return self.user.CallWindowProcW(self.old_proc, hwnd, message, param, handle)

    def take(self):
        result = self.dx, self.dy
        self.dx = self.dy = 0
        return result

    def confine(self, x, y):
        previous = W.RECT()
        if not self.user.GetClipCursor(C.byref(previous)):
            raise C.WinError(C.get_last_error())
        self.clip = previous
        if not self.user.ClipCursor(C.byref(W.RECT(x, y, x + 1, y + 1))):
            raise C.WinError(C.get_last_error())

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.clip is not None:
            self.user.ClipCursor(C.byref(self.clip))
            self.clip = None
        self.user.RegisterRawInputDevices(C.byref(Device(1, 2, 1, None)), 1, C.sizeof(Device))
        if self.old_proc:
            self.set_proc(self.hwnd, -4, self.old_proc)
            self.old_proc = None
