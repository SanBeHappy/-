"""角色主题：槽位定义、主题仓库、帧集解析。

磁盘布局：
    %APPDATA%\\DeskMate\\themes\\<主题id>\\meta.json
    %APPDATA%\\DeskMate\\themes\\<主题id>\\14_cheek.png ...
内置主题 id 固定为 builtin，直接读 exe 里的 assets/char，不落盘、不可写。
自定义主题只存「被替换过」的槽位，其余自动回落到内置图。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap

from config import CONFIG_DIR
from image_proc import SIZE as SLOT_SIZE

BUILTIN_ID = "builtin"
BUILTIN_NAME = "大肥鱼"

# ---------------------------------------------------------------- 槽位

@dataclass(frozen=True)
class Slot:
    key: str
    label: str
    group: str
    usage: str = ""


SLOTS: tuple[Slot, ...] = (
    # 待机
    Slot("14_cheek", "托腮", "idle", "工作日趴在卡片上"),
    Slot("15_hi", "挥手", "idle", "下班之后"),
    # 点击动作
    Slot("06_laugh", "大笑", "action", "跳跃 / 摇摆 / 爱心"),
    Slot("04_wink", "眨眼", "action", "转圈 / 压扁 / 眨眼 / 水花"),
    Slot("05_wave", "招手", "action", "久坐提醒时"),
    Slot("01_angry", "生气", "action", "1.6 秒内连点 5 次"),
    # 长按拎起
    Slot("19_shock", "炸毛", "lift", "刚被拎起来"),
    Slot("20_struggle", "挣扎", "lift", "拎在半空乱蹬"),
    Slot("21_blank", "发呆", "lift", "放下前的收尾之一"),
    Slot("22_dizzy", "晕头", "lift", "放下前的收尾之一"),
    Slot("23_angry", "恼火", "lift", "放下前的收尾之一"),
    Slot("24_cry", "委屈", "lift", "放下前的收尾之一"),
    # 摸头
    Slot("25_shock", "一激灵", "pat", "被碰到的头 0.45 秒"),
    Slot("26_joy", "开心", "pat", "摸头反应"),
    Slot("27_blush", "害羞", "pat", "摸头反应"),
    Slot("28_love", "心动", "pat", "摸头反应"),
    # 拖动摔倒
    Slot("07_stumble", "小碎步", "drag", "慢慢被拖走"),
    Slot("08_tumble", "踉跄", "drag", "中速拖动"),
    Slot("09_faceplant", "拖飞", "drag", "快速拖动"),
    Slot("10_sit", "坐地", "drag", "松手 · 慢速"),
    Slot("11_hurt_sit", "摔懵", "drag", "松手 · 中速"),
    Slot("12_cry", "摔哭", "drag", "松手 · 快速"),
    # 午休吃饭
    Slot("31_cook", "开锅", "meal", "午休刚开始"),
    Slot("32_scoop", "盛饭", "meal", "午休 +1.6 秒"),
    Slot("33_serve", "捧碗", "meal", "午休 +3.2 秒"),
    Slot("34_feast", "猛吃", "meal", "午休满 2 分钟"),
    Slot("35_eat", "扒饭", "meal", "午休满 2 分钟 +1.3 秒"),
    Slot("36_full", "吃撑", "meal", "午休满 2 分钟 +2.6 秒"),
    # 喝水
    Slot("37_hold_cup", "端杯", "drink", "点「喝了」后第 1 帧"),
    Slot("38_raise", "举杯", "drink", "第 2 帧"),
    Slot("39_sip", "抿一口", "drink", "第 3 帧"),
    Slot("40_gulp", "猛喝", "drink", "第 4 帧"),
    Slot("41_ahh", "缓口气", "drink", "第 5 帧"),
    Slot("42_done", "喝完", "drink", "第 6 帧"),
)

SLOT_BY_KEY = {s.key: s for s in SLOTS}
SLOT_KEYS = tuple(SLOT_BY_KEY)

GROUP_ORDER = ("idle", "action", "lift", "pat", "drag", "meal", "drink")
GROUP_TITLES = {
    "idle": "待机",
    "action": "点击动作",
    "lift": "长按拎起",
    "pat": "摸头",
    "drag": "拖动摔倒",
    "meal": "午休吃饭",
    "drink": "喝水",
}
GROUP_HINTS = {
    "idle": "不互动时的样子",
    "action": "点一下或提醒触发的瞬间",
    "lift": "按住角色 2 秒被拎起来",
    "pat": "鼠标移到角色身上",
    "drag": "拖动窗口时按速度切换",
    "meal": "午休时段的吃饭动画",
    "drink": "点「喝了」后的六帧动画",
}


# ---------------------------------------------------------------- 路径


def builtin_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "assets" / "char"
    return Path(__file__).resolve().parent / "assets" / "char"


def themes_root() -> Path:
    root = CONFIG_DIR / "themes"
    root.mkdir(parents=True, exist_ok=True)
    return root


def theme_dir(theme_id: str) -> Path | None:
    if not theme_id or theme_id == BUILTIN_ID:
        return None
    folder = themes_root() / theme_id
    return folder if folder.is_dir() else None


# ---------------------------------------------------------------- 元信息


@dataclass(frozen=True)
class ThemeInfo:
    id: str
    name: str
    builtin: bool
    replaced: int
    total: int
    cover: QPixmap | None

    @property
    def summary(self) -> str:
        if self.builtin:
            return "内置 · 只读"
        if self.replaced == 0:
            return "还没有替换任何槽位"
        return f"已替换 {self.replaced}/{self.total}"


def _read_meta(folder: Path) -> dict:
    try:
        raw = json.loads((folder / "meta.json").read_text("utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _write_meta(folder: Path, data: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "meta.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), "utf-8"
    )


def _count_replaced(folder: Path) -> int:
    return sum(1 for key in SLOT_KEYS if (folder / f"{key}.png").exists())


def _cover(theme_id: str) -> QPixmap | None:
    folder = theme_dir(theme_id)
    if folder is not None:
        own = folder / "14_cheek.png"
        if own.exists():
            pix = QPixmap(str(own))
            if not pix.isNull():
                return pix
    return _builtin_pixmap("14_cheek")


def list_themes() -> list[ThemeInfo]:
    items = [
        ThemeInfo(
            id=BUILTIN_ID,
            name=BUILTIN_NAME,
            builtin=True,
            replaced=0,
            total=len(SLOTS),
            cover=_cover(BUILTIN_ID),
        )
    ]
    root = themes_root()
    found: list[ThemeInfo] = []
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        if not (folder / "meta.json").exists() and _count_replaced(folder) == 0:
            continue  # 空目录/垃圾目录，忽略
        meta = _read_meta(folder)
        found.append(
            ThemeInfo(
                id=folder.name,
                name=str(meta.get("name") or folder.name),
                builtin=False,
                replaced=_count_replaced(folder),
                total=len(SLOTS),
                cover=_cover(folder.name),
            )
        )
    found.sort(key=lambda t: t.name.casefold())
    return items + found


def get_theme(theme_id: str) -> ThemeInfo | None:
    for info in list_themes():
        if info.id == theme_id:
            return info
    return None


def resolve(theme_id: object) -> str:
    """任何非法/已被删掉的值都回落到内置主题。"""
    if isinstance(theme_id, str) and theme_dir(theme_id) is not None:
        return theme_id
    return BUILTIN_ID


def display_name(theme_id: str) -> str:
    resolved = resolve(theme_id)
    if resolved == BUILTIN_ID:
        return BUILTIN_NAME
    meta = _read_meta(themes_root() / resolved)
    return str(meta.get("name") or resolved)


def is_custom(theme_id: str, key: str) -> bool:
    folder = theme_dir(theme_id)
    return folder is not None and (folder / f"{key}.png").exists()


# ---------------------------------------------------------------- 帧集

_BUILTIN_CACHE: dict[str, QPixmap] = {}


def _builtin_pixmap(key: str) -> QPixmap | None:
    if key not in _BUILTIN_CACHE:
        path = builtin_dir() / f"{key}.png"
        _BUILTIN_CACHE[key] = QPixmap(str(path)) if path.exists() else QPixmap()
    pix = _BUILTIN_CACHE[key]
    return None if pix.isNull() else pix


def _normalize(pix: QPixmap) -> QPixmap:
    """手动塞进来的非 384 方图，在内存里纠正成正方形画布，避免被拉伸变形。"""
    if pix.width() == SLOT_SIZE and pix.height() == SLOT_SIZE:
        return pix
    scaled = pix.scaled(
        QSize(SLOT_SIZE, SLOT_SIZE),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QImage(SLOT_SIZE, SLOT_SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawImage(
        (SLOT_SIZE - scaled.width()) // 2, (SLOT_SIZE - scaled.height()) // 2, scaled.toImage()
    )
    painter.end()
    return QPixmap.fromImage(canvas)


def load_frames(theme_id: str) -> dict[str, QPixmap]:
    """永远返回完整键集：主题目录优先，缺的回落到内置。"""
    resolved = resolve(theme_id)
    folder = theme_dir(resolved)
    frames: dict[str, QPixmap] = {}

    for slot in SLOTS:
        pix: QPixmap | None = None
        if folder is not None:
            own = folder / f"{slot.key}.png"
            if own.exists():
                cand = QPixmap(str(own))
                if not cand.isNull():
                    pix = _normalize(cand)
        if pix is None:
            pix = _builtin_pixmap(slot.key)
        if pix is not None:
            frames[slot.key] = pix

    # 兜底：内置目录里其余未声明的图也带上，防止任何拼写落空
    for path in sorted(builtin_dir().glob("*.png")):
        if path.stem in frames:
            continue
        pix = _builtin_pixmap(path.stem)
        if pix is not None:
            frames[path.stem] = pix

    return frames


# ---------------------------------------------------------------- 校验

_BAD_CHARS = re.compile(r'[\\/:*?"<>|]')


def valid_name(name: str, exclude_id: str = "") -> tuple[bool, str]:
    name = (name or "").strip()
    if not name:
        return False, "请输入主题名称"
    if len(name) > 24:
        return False, "名称最多 24 个字"
    if _BAD_CHARS.search(name):
        return False, '名称不能包含 \\ / : * ? " < > |'
    folded = name.casefold()
    for info in list_themes():
        if info.id == exclude_id:
            continue
        if info.name.casefold() == folded or info.id.casefold() == folded:
            return False, "已经有同名主题了"
    return True, ""


def _safe_folder_name(name: str) -> str:
    base = _BAD_CHARS.sub("", name).strip().strip(".") or "theme"
    base = base[:40]
    root = themes_root()
    candidate = base
    index = 2
    while (root / candidate).exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def _require_custom(theme_id: str) -> Path:
    folder = theme_dir(theme_id)
    if folder is None:
        raise PermissionError("内置主题不能修改，请先新建一个主题")
    return folder


# ---------------------------------------------------------------- 写操作


def create_theme(name: str, copy_builtin: bool = False) -> ThemeInfo:
    ok, msg = valid_name(name)
    if not ok:
        raise ValueError(msg)
    name = name.strip()
    folder = themes_root() / _safe_folder_name(name)
    folder.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    _write_meta(folder, {"name": name, "created": now, "updated": now, "version": 1})

    if copy_builtin:
        for key in SLOT_KEYS:
            src = builtin_dir() / f"{key}.png"
            if src.exists():
                shutil.copy2(src, folder / f"{key}.png")

    info = get_theme(folder.name)
    assert info is not None
    return info


def rename_theme(theme_id: str, new_name: str) -> ThemeInfo:
    folder = _require_custom(theme_id)
    ok, msg = valid_name(new_name, exclude_id=theme_id)
    if not ok:
        raise ValueError(msg)
    meta = _read_meta(folder)
    meta["name"] = new_name.strip()
    meta["updated"] = datetime.now().isoformat(timespec="seconds")
    meta.setdefault("version", 1)
    _write_meta(folder, meta)
    info = get_theme(theme_id)
    assert info is not None
    return info


def delete_theme(theme_id: str) -> None:
    folder = _require_custom(theme_id)
    shutil.rmtree(folder, ignore_errors=True)


def set_slot(theme_id: str, key: str, image: QImage) -> None:
    folder = _require_custom(theme_id)
    if key not in SLOT_BY_KEY:
        raise KeyError(key)
    from image_proc import save_png

    save_png(image, folder / f"{key}.png")
    meta = _read_meta(folder)
    meta["updated"] = datetime.now().isoformat(timespec="seconds")
    _write_meta(folder, meta)


def reset_slot(theme_id: str, key: str) -> None:
    folder = _require_custom(theme_id)
    target = folder / f"{key}.png"
    if target.exists():
        try:
            os.remove(target)
        except OSError:
            pass


def reset_all(theme_id: str) -> None:
    folder = _require_custom(theme_id)
    for key in SLOT_KEYS:
        reset_slot(theme_id, key)
    meta = _read_meta(folder)
    meta["updated"] = datetime.now().isoformat(timespec="seconds")
    _write_meta(folder, meta)


def open_folder(theme_id: str) -> None:
    """在资源管理器里打开主题目录（调试/高级用户用）。"""
    folder = theme_dir(theme_id)
    if folder is None:
        return
    try:
        os.startfile(str(folder))  # noqa: S606  (Windows only)
    except Exception:
        pass
