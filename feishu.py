"""一键打开飞书桌面端。

优先走 feishu:// 协议（跟点飞书链接等价，已经开着就直接激活窗口）；
协议没注册或启动失败时，再从注册表和常见安装目录里找 Feishu.exe 直接拉起。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PROTOCOL = "feishu://"

# 常见安装位置（相对环境变量）
_RELATIVE = (
    r"Feishu\Feishu.exe",
    r"Feishu\app\Feishu.exe",
    r"Programs\Feishu\Feishu.exe",
    r"Lark\Lark.exe",
    r"Lark\app\Lark.exe",
)

_ENVS = ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "APPDATA", "PROGRAMW6432")


def _no_window() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _exe_from_registry() -> list[str]:
    """从 feishu:// / lark:// 的协议注册信息里抠出 exe 路径。"""
    if sys.platform != "win32":
        return []
    try:
        import winreg
    except ImportError:
        return []

    found: list[str] = []
    for name in ("feishu", "lark"):
        try:
            with winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT, rf"{name}\shell\open\command"
            ) as key:
                command = winreg.QueryValueEx(key, None)[0]
        except OSError:
            continue
        match = re.search(r'"([^"]+\.exe)"', command) or re.search(
            r"([A-Za-z]:\\[^\s\"]+\.exe)", command
        )
        if match:
            found.append(match.group(1))
    return found


def _known_paths() -> list[str]:
    paths: list[str] = []
    for env in _ENVS:
        base = os.environ.get(env)
        if not base:
            continue
        for rel in _RELATIVE:
            paths.append(str(Path(base) / rel))
    return paths


def find_exe() -> str | None:
    """按 注册表 → 常见目录 的顺序找飞书可执行文件。"""
    for candidate in _exe_from_registry() + _known_paths():
        try:
            if candidate and Path(candidate).is_file():
                return candidate
        except OSError:
            continue
    return None


def open_feishu() -> tuple[bool, str]:
    """返回 (是否成功, 说明)。成功时说明里是走的方式，方便写日志。"""
    if sys.platform != "win32":
        return False, "只支持 Windows"

    # 1) 协议：最省事，飞书自己在跑的话会直接激活主窗口
    try:
        os.startfile(PROTOCOL)  # noqa: S606 - 打开已注册的协议
        return True, PROTOCOL
    except OSError:
        pass

    # 2) 找 exe 直接启动
    exe = find_exe()
    if exe is None:
        return False, "没找到飞书客户端，可能没装"
    try:
        subprocess.Popen([exe], creationflags=_no_window())
    except OSError as exc:
        return False, f"启动失败：{exc}"
    return True, exe
