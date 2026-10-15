import ctypes
from ctypes import wintypes
import sys

_handle = None


def acquire_installed_instance() -> bool:
    global _handle
    if not getattr(sys, "frozen", False):
        return True
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateMutexW.argtypes = (ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    ctypes.set_last_error(0)
    _handle = kernel.CreateMutexW(None, False, "Local\\seoul2lineToolboxApp")
    if not _handle:
        raise ctypes.WinError(ctypes.get_last_error())
    return ctypes.get_last_error() != 183
