"""下班收尾：关掉微信 → 回到桌面 → 关闭显示器。

三步都是系统级操作，失败不抛异常，统一返回 (是否成功, 说明)，由调用方写日志。
自动关机的那天不执行这一套（见 main._maybe_wrapup）。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
from ctypes import wintypes

# 微信 4.x 是 Weixin.exe，3.x 是 WeChat.exe，两个都试
WECHAT_PROCESSES = ("Weixin.exe", "WeChat.exe")

HWND_BROADCAST = 0xFFFF
WM_SYSCOMMAND = 0x0112
SC_MONITORPOWER = 0xF170
SMTO_ABORTIFHUNG = 0x0002

VK_LWIN = 0x5B
VK_D = 0x44
KEYEVENTF_KEYUP = 0x0002


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _taskkill(name: str, force: bool) -> int:
    """返回 taskkill 的退出码：0 表示至少关掉了一个进程。"""
    command = ["taskkill", "/IM", name]
    if force:
        command.insert(1, "/F")
    try:
        proc = subprocess.run(
            command, capture_output=True, creationflags=_no_window(), timeout=10
        )
        return proc.returncode
    except (OSError, subprocess.TimeoutExpired):
        return 1


def close_wechat() -> tuple[bool, str]:
    """先礼后兵：先发关闭消息，1.2 秒后还在就强杀。"""
    if sys.platform != "win32":
        return False, "只支持 Windows"

    closed: list[str] = []
    for name in WECHAT_PROCESSES:
        if _taskkill(name, force=False) == 0:
            closed.append(name)

    if not closed:
        return False, "微信没在运行"

    time.sleep(1.2)
    forced: list[str] = []
    for name in closed:
        if _taskkill(name, force=False) != 0:
            if _taskkill(name, force=True) == 0:
                forced.append(name)

    detail = "已关闭 " + "、".join(closed)
    if forced:
        detail += "（" + "、".join(forced) + " 强制结束）"
    return True, detail


def _at_desktop() -> bool:
    """当前焦点是不是已经在桌面（Progman / WorkerW）。"""
    try:
        user32 = ctypes.windll.user32
    except AttributeError:
        return False
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    return buf.value in ("Progman", "WorkerW")


def show_desktop() -> tuple[bool, str]:
    """按 Win+D 回桌面；已经在桌面就不按（再按一次会把窗口还原回来）。"""
    if sys.platform != "win32":
        return False, "只支持 Windows"
    if _at_desktop():
        return True, "已经在桌面"
    try:
        user32 = ctypes.windll.user32
        user32.keybd_event(VK_LWIN, 0, 0, 0)
        user32.keybd_event(VK_D, 0, 0, 0)
        user32.keybd_event(VK_D, 0, KEYEVENTF_KEYUP, 0)
        user32.keybd_event(VK_LWIN, 0, KEYEVENTF_KEYUP, 0)
    except (AttributeError, OSError) as exc:
        return False, f"模拟按键失败：{exc}"
    return True, "已回到桌面"


def monitor_off() -> tuple[bool, str]:
    """广播「关闭显示器」，效果等同电源按钮里的关屏。

    动鼠标或敲键盘就亮回来；少数显卡/显示器组合会忽略这条消息。
    """
    if sys.platform != "win32":
        return False, "只支持 Windows"
    try:
        user32 = ctypes.windll.user32
        result = user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SYSCOMMAND,
            SC_MONITORPOWER,
            2,                      # 2 = 关闭显示器
            SMTO_ABORTIFHUNG,
            1000,
            None,
        )
    except (AttributeError, OSError) as exc:
        return False, f"调用失败：{exc}"
    if not result:
        return False, "系统没有响应关屏消息"
    return True, "已发送关屏"


def is_wechat_running() -> bool:
    """给设置面板的按钮做提示用：微信在不在跑。"""
    for name in WECHAT_PROCESSES:
        try:
            proc = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}"],
                capture_output=True,
                creationflags=_no_window(),
                timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        text = (proc.stdout or b"").decode("mbcs", "ignore")
        if name.lower() in text.lower():
            return True
    return False
