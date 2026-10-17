"""Raw mouse deltas collected off the Tk thread; foreground packets only."""
import ctypes as C
from ctypes import wintypes as W
import threading
import time


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
        self.lock = threading.Lock()
        self.packets = 0
        self.last_packet = None
        self.pending_since = None
        self.consumed_age_ms = 0.0
        self.closed = False
        self.user = C.WinDLL("user32", use_last_error=True)
        self.user.RegisterRawInputDevices.argtypes = [C.POINTER(Device), W.UINT, W.UINT]
        self.user.RegisterRawInputDevices.restype = W.BOOL
        self.user.GetRawInputData.argtypes = [W.HANDLE, W.UINT, W.LPVOID, C.POINTER(W.UINT), W.UINT]
        self.user.GetRawInputData.restype = W.UINT
        self.user.DefWindowProcW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
        self.user.DefWindowProcW.restype = C.c_ssize_t
        self.user.ClipCursor.argtypes = [C.POINTER(W.RECT)]
        self.user.ClipCursor.restype = W.BOOL
        self.user.GetClipCursor.argtypes = [C.POINTER(W.RECT)]
        self.user.GetClipCursor.restype = W.BOOL
        self.user.GetAncestor.argtypes = [W.HWND, W.UINT]
        self.user.GetAncestor.restype = W.HWND
        self.user.GetForegroundWindow.restype = W.HWND
        self.user.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
        self.user.GetClientRect.restype = W.BOOL
        self.user.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
        self.user.ClientToScreen.restype = W.BOOL
        self.clip = None
        from app.games.aim_trainer.raw_collector import RawCollector
        self.collector = RawCollector(self)

    def _receive(self, hwnd, message, param, handle):
        if message == 0x00FF and not self.closed:
            try:
                packet, size = Packet(), W.UINT(C.sizeof(Packet))
                count = self.user.GetRawInputData(handle, 0x10000003, C.byref(packet), C.byref(size), C.sizeof(Header))
                if count == 0xFFFFFFFF:
                    raise C.WinError(C.get_last_error())
                if count >= C.sizeof(Packet) and packet.header.kind == 0 and self.is_foreground():
                    if packet.mouse.flags & 1:
                        self.error = "상대 이동을 지원하는 마우스가 필요합니다."
                    else:
                        with self.lock:
                            now = time.perf_counter()
                            if self.pending_since is None:
                                self.pending_since = now
                            self.dx += packet.mouse.x
                            self.dy += packet.mouse.y
                            self.packets += 1
                            self.last_packet = now
            except Exception as exc:
                self.error = str(exc)
        return self.user.DefWindowProcW(hwnd, message, param, handle)

    def take(self):
        with self.lock:
            if self.pending_since is not None:
                self.consumed_age_ms = (time.perf_counter() - self.pending_since) * 1000
                self.pending_since = None
            result = self.dx, self.dy
            self.dx = self.dy = 0
            return result

    def metrics(self):
        with self.lock:
            return self.packets, self.last_packet, self.consumed_age_ms

    def is_foreground(self):
        return not self.closed and self.user.GetForegroundWindow() == self.user.GetAncestor(self.hwnd, 2)

    def confine(self, x, y):
        if self.clip is None:
            previous = W.RECT()
            if not self.user.GetClipCursor(C.byref(previous)):
                raise C.WinError(C.get_last_error())
            self.clip = previous
        if not self.user.ClipCursor(C.byref(W.RECT(x, y, x + 1, y + 1))):
            raise C.WinError(C.get_last_error())

    def confine_center(self):
        if not self.is_foreground():
            return False
        client = W.RECT()
        if not self.user.GetClientRect(self.hwnd, C.byref(client)):
            raise C.WinError(C.get_last_error())
        point = W.POINT((client.left + client.right) // 2, (client.top + client.bottom) // 2)
        if not self.user.ClientToScreen(self.hwnd, C.byref(point)):
            raise C.WinError(C.get_last_error())
        self.confine(point.x, point.y)
        return True

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.clip is not None:
            self.user.ClipCursor(C.byref(self.clip))
            self.clip = None
        self.collector.close()
