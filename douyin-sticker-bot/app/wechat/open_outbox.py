"""微信侧：打开文件夹、把微信窗口拉到前台。"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path

WEIXIN_EXE = Path(r"C:\Program Files\Tencent\Weixin\Weixin.exe")


def open_folder(path: Path) -> None:
    os.startfile(str(path))  # noqa: S606  (Windows 专用)


def wechat_running() -> bool:
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Weixin.exe"],
            capture_output=True, text=True, timeout=10, check=False,
        ).stdout
        return "Weixin.exe" in out
    except Exception:  # noqa: BLE001
        return False


def launch_wechat() -> bool:
    if wechat_running():
        return True
    if not WEIXIN_EXE.exists():
        return False
    subprocess.Popen([str(WEIXIN_EXE)], close_fds=True)  # noqa: S603
    return True


SW_RESTORE = 9


def focus_wechat() -> bool:
    """按窗口标题找微信主窗并置前。"""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _lparam):  # noqa: ANN001
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value
        if title in ("微信", "WeChat", "Weixin", "微信（Windows）"):
            found.append(hwnd)
        return True

    user32.EnumWindows(cb, 0)
    if not found:
        return False
    hwnd = found[0]
    user32.ShowWindow(hwnd, SW_RESTORE)
    try:
        user32.SetForegroundWindow(hwnd)
    except Exception:  # noqa: BLE001
        pass
    return True


def prepare_import(files: list[Path], outbox: Path) -> int:
    """把成品平铺复制进 outbox，返回数量。"""
    outbox.mkdir(parents=True, exist_ok=True)
    for old in outbox.iterdir():
        if old.is_file():
            try:
                old.unlink()
            except OSError:
                pass
    n = 0
    for f in files:
        if not f.exists():
            continue
        n += 1
        target = outbox / f"{n:03d}{f.suffix.lower()}"
        try:
            os.link(f, target)  # 硬链接，省空间
        except OSError:
            import shutil
            shutil.copy2(f, target)
    return n
