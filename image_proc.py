"""图片导入流水线：任意图片 → 384×384 透明 PNG。

用户可能丢进来白底 JPG、手机照片、几百 KB 的网图，这里统一处理：
  读取（吃 EXIF 方向）→ 压到 896 → 四角判白底 → 行扫描 flood fill 抠背景
  → 边缘亮度渐变 + 反白混合 → 等比缩放居中到 384² → 原子写盘

只依赖 QtGui，不引第三方库（环境里没有 Pillow / numpy）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QImage, QImageReader, QPainter

SIZE = 384
MAX_SIDE = 896          # 处理前先把最长边压到这里，控住 flood fill 的耗时
MAX_FILE_MB = 60

WHITE_LEVEL = 236       # r/g/b 都超过它才算白
WHITE_SPREAD = 16       # max-min 小于它才算白（排除浅彩色）
CORNER_BOX = 24         # 四角检测方块边长
CORNER_RATIO = 0.92     # 每个角的白像素占比阈值
EDGE_BAND = 2           # 边缘抗白边的带宽（像素）


class ImageImportError(Exception):
    """图片无法使用，消息直接展示给用户。"""


@dataclass(frozen=True)
class ImportResult:
    image: QImage
    removed_bg: bool
    src_size: tuple[int, int]
    upscaled: bool

    @property
    def note(self) -> str:
        w, h = self.src_size
        head = "已自动去除白底" if self.removed_bg else "未检测到白底，仅做缩放"
        text = f"{head} · {w}×{h} → {SIZE}×{SIZE}"
        if self.upscaled:
            text += " · 原图偏小，放大后可能略糊"
        return text


# ---------------------------------------------------------------- 读取


def _read(path: Path) -> QImage:
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except OSError:
        raise ImageImportError("读不到这个文件，可能已被移动或没有权限")
    if size_mb > MAX_FILE_MB:
        raise ImageImportError(f"图片太大（{size_mb:.0f} MB），请先压缩到 {MAX_FILE_MB} MB 以内")

    reader = QImageReader(str(path))
    reader.setAutoTransform(True)          # 按 EXIF 摆正手机照片
    img = reader.read()
    if img.isNull():
        raise ImageImportError("无法读取这张图，可能不是图片或文件已损坏")
    return img


def _limit(img: QImage, side: int) -> QImage:
    if max(img.width(), img.height()) <= side:
        return img
    return img.scaled(
        QSize(side, side),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


# ---------------------------------------------------------------- 白底判定


def _is_white(r: int, g: int, b: int) -> bool:
    return (
        r > WHITE_LEVEL
        and g > WHITE_LEVEL
        and b > WHITE_LEVEL
        and max(r, g, b) - min(r, g, b) < WHITE_SPREAD
    )


def _corners_are_white(img: QImage) -> bool:
    """四个角都是白才算白底图 —— 白围裙在中间，不会被误判。"""
    src = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = src.width(), src.height()
    if w < CORNER_BOX * 2 or h < CORNER_BOX * 2:
        return False
    stride = src.bytesPerLine()
    buf = bytes(src.constBits())

    corners = (
        (0, 0),
        (w - CORNER_BOX, 0),
        (0, h - CORNER_BOX),
        (w - CORNER_BOX, h - CORNER_BOX),
    )
    total = CORNER_BOX * CORNER_BOX
    for ox, oy in corners:
        white = 0
        for y in range(oy, oy + CORNER_BOX):
            row = y * stride
            for x in range(ox, ox + CORNER_BOX):
                p = row + x * 4
                if _is_white(buf[p], buf[p + 1], buf[p + 2]):
                    white += 1
        if white / total < CORNER_RATIO:
            return False
    return True


# ---------------------------------------------------------------- 抠图


def _flood_remove_white(img: QImage) -> QImage:
    """从四条边做行扫描填充，只清与外界连通的白色。"""
    src = img.convertToFormat(QImage.Format.Format_RGBA8888)
    w, h = src.width(), src.height()
    stride = src.bytesPerLine()
    buf = bytearray(bytes(src.constBits()))     # 必须拷贝，constBits 的内存不能改
    seen = bytearray(w * h)

    def white(p: int) -> bool:
        return _is_white(buf[p], buf[p + 1], buf[p + 2])

    stack: list[tuple[int, int]] = []
    for x in range(w):
        stack.append((x, 0))
        stack.append((x, h - 1))
    for y in range(h):
        stack.append((0, y))
        stack.append((w - 1, y))

    while stack:
        x, y = stack.pop()
        row = y * stride
        if seen[y * w + x] or not white(row + x * 4):
            continue

        left = x
        while left > 0 and not seen[y * w + left - 1] and white(row + (left - 1) * 4):
            left -= 1
        right = x
        while right < w - 1 and not seen[y * w + right + 1] and white(row + (right + 1) * 4):
            right += 1

        for i in range(left, right + 1):
            seen[y * w + i] = 1
            buf[row + i * 4 + 3] = 0

        if y > 0:
            base = (y - 1) * w
            for i in range(left, right + 1):
                if not seen[base + i]:
                    stack.append((i, y - 1))
        if y < h - 1:
            base = (y + 1) * w
            for i in range(left, right + 1):
                if not seen[base + i]:
                    stack.append((i, y + 1))

    # 边缘 2px：亮度 → alpha 渐变 + 反白混合，消掉一圈灰白描边
    for y in range(h):
        row = y * stride
        for x in range(w):
            idx = y * w + x
            if seen[idx]:
                continue
            near = False
            for dy in range(-EDGE_BAND, EDGE_BAND + 1):
                ny = y + dy
                if ny < 0 or ny >= h:
                    continue
                base = ny * w
                for dx in range(-EDGE_BAND, EDGE_BAND + 1):
                    nx = x + dx
                    if 0 <= nx < w and seen[base + nx]:
                        near = True
                        break
                if near:
                    break
            if not near:
                continue

            p = row + x * 4
            r, g, b = buf[p], buf[p + 1], buf[p + 2]
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            a = (252.0 - lum) / 26.0
            a = 0.0 if a < 0.0 else (1.0 if a > 1.0 else a)
            if a <= 0.02:
                buf[p + 3] = 0
                continue
            inv = 255.0 * (1.0 - a)
            for k, c in enumerate((r, g, b)):
                val = (c - inv) / a
                buf[p + k] = 0 if val < 0 else (255 if val > 255 else int(val))
            buf[p + 3] = int(a * 255)

    out = QImage(bytes(buf), w, h, stride, QImage.Format.Format_RGBA8888)
    return out.copy()      # 脱离 buf 生命周期，否则 GC 后图像会变黑


# ---------------------------------------------------------------- 收尾


def _fit_center(img: QImage, size: int = SIZE) -> QImage:
    scaled = img.scaled(
        QSize(size, size),
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
    canvas = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.GlobalColor.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    painter.drawImage((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return canvas


def process_image(path: str | Path) -> ImportResult:
    """完整流水线：读 → 判白底 → 抠图 → 缩放居中。"""
    img = _read(Path(path))
    src_size = (img.width(), img.height())
    upscaled = max(src_size) < SIZE

    img = _limit(img, MAX_SIDE)
    removed = False
    if _corners_are_white(img):
        img = _flood_remove_white(img)
        removed = True

    return ImportResult(_fit_center(img, SIZE), removed, src_size, upscaled)


def save_png(img: QImage, dst: Path) -> None:
    """原子写入，同名覆盖也安全。"""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        if not img.save(str(tmp), "PNG"):
            raise OSError("写入图片失败，请检查磁盘空间与权限")
        os.replace(tmp, dst)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
