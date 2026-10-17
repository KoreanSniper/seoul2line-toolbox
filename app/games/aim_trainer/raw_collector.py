"""A message-only Win32 window on a dedicated input thread, without Tcl/Tk."""
import ctypes as C
from ctypes import wintypes as W
import threading
import uuid


class WindowClass(C.Structure):
    _fields_ = [("style", W.UINT), ("proc", C.c_void_p), ("class_extra", C.c_int),
                ("window_extra", C.c_int), ("instance", W.HINSTANCE), ("icon", W.HICON),
                ("cursor", W.HANDLE), ("background", W.HBRUSH), ("menu", W.LPCWSTR), ("name", W.LPCWSTR)]


class RawCollector:
    def __init__(self, owner):
        self.owner = owner
        self.user = owner.user
        self.window = None
        self.thread_id = None
        self.ready = threading.Event()
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.kernel.GetModuleHandleW.argtypes = [W.LPCWSTR]
        self.kernel.GetModuleHandleW.restype = W.HINSTANCE
        self.kernel.GetCurrentThreadId.restype = W.DWORD
        signatures = {
            'RegisterClassW': ([C.POINTER(WindowClass)], W.ATOM),
            'UnregisterClassW': ([W.LPCWSTR, W.HINSTANCE], W.BOOL),
            'CreateWindowExW': ([W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD, C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, W.LPVOID], W.HWND),
            'DestroyWindow': ([W.HWND], W.BOOL),
            'GetMessageW': ([C.POINTER(W.MSG), W.HWND, W.UINT, W.UINT], C.c_int),
            'DispatchMessageW': ([C.POINTER(W.MSG)], C.c_ssize_t),
            'PostThreadMessageW': ([W.DWORD, W.UINT, W.WPARAM, W.LPARAM], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user, name)
            function.argtypes, function.restype = args, result
        proc_type = C.WINFUNCTYPE(C.c_ssize_t, W.HWND, W.UINT, W.WPARAM, W.LPARAM)
        self.callback = proc_type(owner._receive)
        self.thread = threading.Thread(target=self.run, name='AimRawInput', daemon=True)
        self.thread.start()
        if not self.ready.wait(3) or owner.error:
            owner.closed = True
            self.close()
            raise OSError(owner.error or '마우스 입력 스레드 시작 시간이 초과되었습니다.')

    def run(self):
        from app.games.aim_trainer.raw_mouse import Device
        instance = self.kernel.GetModuleHandleW(None)
        name = 'ToolboxAimRaw_' + uuid.uuid4().hex
        registered, atom = False, 0
        try:
            self.thread_id = self.kernel.GetCurrentThreadId()
            window_class = WindowClass(0, C.cast(self.callback, C.c_void_p).value, 0, 0, instance, None, None, None, None, name)
            atom = self.user.RegisterClassW(C.byref(window_class))
            if not atom:
                raise C.WinError(C.get_last_error())
            self.window = self.user.CreateWindowExW(0, name, name, 0, 0, 0, 0, 0, W.HWND(-3), None, instance, None)
            if not self.window:
                raise C.WinError(C.get_last_error())
            # INPUTSINK routes to this private queue. The owner drops packets
            # whenever its training window is not the foreground application.
            if not self.owner.closed:
                registered = bool(self.user.RegisterRawInputDevices(C.byref(Device(1, 2, 0x100, self.window)), 1, C.sizeof(Device)))
                if not registered:
                    raise C.WinError(C.get_last_error())
            self.ready.set()
            message = W.MSG()
            while not self.owner.closed:
                result = self.user.GetMessageW(C.byref(message), None, 0, 0)
                if result == -1:
                    raise C.WinError(C.get_last_error())
                if result == 0:
                    break
                self.user.DispatchMessageW(C.byref(message))
        except Exception as exc:
            self.owner.error = str(exc)
        finally:
            if registered:
                self.user.RegisterRawInputDevices(C.byref(Device(1, 2, 1, None)), 1, C.sizeof(Device))
            if self.window:
                self.user.DestroyWindow(self.window)
                self.window = None
            if atom:
                self.user.UnregisterClassW(name, instance)
            self.ready.set()

    def close(self):
        if self.thread_id:
            self.user.PostThreadMessageW(self.thread_id, 0x12, 0, 0)
        if threading.current_thread() is not self.thread:
            self.thread.join(timeout=2)
