"""配置持久化与开机自启。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

APP_NAME = "DeskMate"
APP_TITLE = "工位伴侣"
APP_VERSION = "1.0.17"

def _resolve_data_dir() -> Path:
    """默认存 %APPDATA%；如果 exe 旁边有 portable.txt，就存到 exe 同级的 DeskMate-data。

    便携用法：把 exe 和一个空的 portable.txt 放在一起，配置、主题都会跟着走，
    整个文件夹拷到别的电脑就能继续用。
    """
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        if (exe_dir / "portable.txt").exists():
            return exe_dir / "DeskMate-data"
    return Path(os.environ.get("APPDATA") or Path.home()) / APP_NAME


CONFIG_DIR = _resolve_data_dir()
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULTS: dict = {
    # 作息
    "start_work": "09:30",
    "off_work": "18:00",
    "pre_alert_min": 15,
    "work_days": [0, 1, 2, 3, 4],
    # 久坐
    "sit_enabled": True,
    "sit_interval": 45,
    "sit_snooze": 5,
    "lunch_enabled": True,
    "lunch_start": "12:00",
    "lunch_end": "13:30",
    # 喝水
    "drink_enabled": True,
    "drink_interval": 30,
    "drink_cups": 0,
    "drink_cups_date": "",
    # 周报
    "weekly_report_enabled": True,
    "weekly_report_time": "17:40",
    "report_done_date": "",
    # 天气
    "weather_city": "",
    # 角色
    "char_theme": "builtin",
    # 其它
    "sound": True,
    "autostart": False,
    "pos": None,
}


class Config:
    """极简 dict 封装，读不到就用默认值。"""

    def __init__(self) -> None:
        self._d = dict(DEFAULTS)
        self.load()

    def load(self) -> None:
        try:
            raw = json.loads(CONFIG_FILE.read_text("utf-8"))
        except Exception:
            return
        if isinstance(raw, dict):
            for key in DEFAULTS:
                if key in raw:
                    self._d[key] = raw[key]

    def save(self) -> None:
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(
                json.dumps(self._d, ensure_ascii=False, indent=2), "utf-8"
            )
        except Exception:
            pass

    def __getitem__(self, key):
        return self._d.get(key, DEFAULTS.get(key))

    def __setitem__(self, key, value) -> None:
        self._d[key] = value

    def update(self, mapping: dict) -> None:
        self._d.update(mapping)


# ---------------------------------------------------------------- 开机自启

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    python = Path(sys.executable)
    pythonw = python.with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else python
    script = Path(__file__).resolve().parent / "main.py"
    return f'"{exe}" "{script}"'


def set_autostart(enabled: bool) -> bool:
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            if enabled:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False


def is_autostart() -> bool:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except Exception:
        return False
