"""DeepSeek「蓝色大肥鱼」Q 版形象（图片驱动版）。

素材位于 assets/char/，由两张精灵表切分并抠去白底：
- 01~06 站立表情差分
- 07~12 拖拽时的摔倒序列

角色不是独立窗口——由 MainCard 在自绘时先画角色、再画卡片，
于是角色的下半身被卡片自然挡住，形成「从窗口后面抱住窗口」的效果。
"""

from __future__ import annotations

import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap

import char_theme

# ---------------------------------------------------------------- 资源

CHAR_BOX = 188.0          # 角色绘制方框边长（素材是正方形）
CHAR_TOP = 2.0            # 方框在窗口里的顶部 y

IDLE_EXPR = "14_cheek"      # 平常就趴在窗口上托腮
OFF_IDLE_EXPR = "15_hi"     # 下班后趴在窗口挥手     # 下班后待机就举着手打招呼

ACTION_EXPR = {
    "hop": ("06_laugh",),
    "wiggle": ("06_laugh",),
    "spin": ("04_wink",),
    "squish": ("04_wink",),
    "wink": ("04_wink",),
    "love": ("06_laugh",),
    "splash": ("04_wink",),
    "dizzy": ("04_wink",),
    "annoyed": ("01_angry",),     # 生气只留给连点
    "wave": ("05_wave",),
}

# 长按拎起：按时间依次切帧，最后一个是随机的收尾情绪
LIFT_DURATION = 2.9
LIFT_STAGES = ((0.0, 0.72, "19_shock"), (0.72, 1.52, "20_struggle"))
LIFT_ENDINGS = ("21_blank", "22_dizzy", "23_angry", "24_cry")

MEAL_EARLY = ("31_cook", "32_scoop", "33_serve")     # 开锅 → 盛饭 → 捧碗
MEAL_LATE = ("34_feast", "35_eat", "36_full")        # 猛吃 → 扒饭 → 吃撑
MEAL_EARLY_STEP = 1.6      # 前段每张停这么久
MEAL_LATE_STEP = 1.3       # 后段吃得更快
MEAL_SWITCH = 120.0        # 午休开始 2 分钟后切换

PAT_WINDOW = 2.2       # 摸头反应持续多久
PAT_REACTIONS = ("26_joy", "27_blush", "28_love")

POKE_LIMIT = 5        # 连点几次才生气
POKE_WINDOW = 1.6      # 间隔超过这个秒数就重新计数

ACTIONS = ("hop", "wiggle", "spin", "squish", "wink", "love", "splash", "dizzy")
DURATION = {
    "hop": 0.78,
    "wiggle": 1.0,
    "spin": 0.95,
    "squish": 0.62,
    "wink": 0.95,
    "love": 1.5,
    "splash": 1.25,
    "dizzy": 1.25,
    "annoyed": 0.95,
    "wave": 2.6,
    "recover": 1.9,
    "stand_up": 0.42,
    "lift": LIFT_DURATION,
    "pat": PAT_WINDOW,
}

# 个别帧需要整体偏移，免得关键部位被卡片切掉
EXPR_OFFSET = {
    "09_faceplant": -20.0,   # 趴地时把脸抬出来
    "08_tumble": -6.0,
}

# 拖动速度 → 摔倒帧（像素/秒）
DRAG_SLOW = 420
DRAG_FAST = 1150


def _heart_path(size: float) -> QPainterPath:
    path = QPainterPath()
    path.moveTo(0, size * 0.42)
    path.cubicTo(-size * 0.62, -size * 0.1, -size * 0.34, -size * 0.62, 0, -size * 0.22)
    path.cubicTo(size * 0.34, -size * 0.62, size * 0.62, -size * 0.1, 0, size * 0.42)
    return path


@dataclass
class Particle:
    x: float
    y: float
    vx: float
    vy: float
    life: float
    total: float
    kind: str
    size: float
    spin: float = 0.0


class FishState:
    """小肥鱼状态机：表情、动作变换、拖拽反应、粒子。"""

    def __init__(self, theme_id: str = char_theme.BUILTIN_ID) -> None:
        self.theme_id = char_theme.BUILTIN_ID
        self.frames: dict[str, QPixmap] = {}
        self.idle_expr = IDLE_EXPR
        self.expr = IDLE_EXPR
        self.t = 0.0
        self.action: str | None = None
        self.action_start = 0.0
        self.action_duration = 1.0
        self.last_click = -10.0
        self.particles: list[Particle] = []
        self.happy = 0.0
        self.hover = False

        self.meal = False
        self.meal_start = 0.0
        self.dragging = False
        self.drag_speed = 0.0
        self._clicks: list[float] = []
        self.use_theme(theme_id)

    def use_theme(self, theme_id: str) -> None:
        """切换角色主题。帧集换了，正在播放的动作作废。"""
        frames = char_theme.load_frames(theme_id)
        if not frames:                 # 素材全丢时保留旧图，别黑屏
            return
        self.theme_id = char_theme.resolve(theme_id)
        self.frames = frames

        self.action = None             # 播到一半的动作作废，避免帧映射错位
        self.happy = 0.0
        self._clicks.clear()
        self.particles.clear()
        # dragging 不动：卡片那边 _drag_offset 还在，擅自复位会状态错步

        if self.idle_expr not in frames:
            self.idle_expr = IDLE_EXPR if IDLE_EXPR in frames else next(iter(frames), "")
        if not self.dragging:
            self.expr = self._meal_frame() if self.meal else self.idle_expr

    # ------------------------------------------------------------ 驱动

    def tick(self, dt: float) -> None:
        self.t += dt

        if self.action == "pat":
            elapsed = self.t - self.action_start
            self.expr = "25_shock" if elapsed < 0.45 else self._pat_expr

        if self.action == "lift":
            elapsed = self.t - self.action_start
            for start, end, name in LIFT_STAGES:
                if start <= elapsed < end:
                    self.expr = name
                    break
            else:
                self.expr = self._lift_ending

        if self.action:
            if self.t - self.action_start >= self.action_duration:
                if self.action == "recover":
                    self.action = "stand_up"
                    self.action_start = self.t
                    self.action_duration = DURATION["stand_up"]
                    self.expr = self.idle_expr
                else:
                    self.action = None
                    if not self.dragging:
                        self.expr = self.idle_expr

        if self.happy > 0:
            self.happy = max(0.0, self.happy - dt * 1.2)

        if not self.action and not self.dragging:
            self.expr = self._meal_frame() if self.meal else self.idle_expr

        alive: list[Particle] = []
        for p in self.particles:
            p.life -= dt
            if p.life <= 0:
                continue
            if p.kind == "drop":
                p.vy += 210 * dt
                p.vx *= 0.985
            elif p.kind == "heart":
                p.vx *= 0.97
                p.vy *= 0.985
            p.x += p.vx * dt
            p.y += p.vy * dt
            alive.append(p)
        self.particles = alive

    def set_look(self, dx: float, dy: float) -> None:
        """素材表情固定，保留接口但不再使用。"""

    def set_idle(self, expr: str) -> None:
        """切换待机表情（下班后换成挥手）。"""
        if expr == self.idle_expr or expr not in self.frames:
            return
        self.idle_expr = expr
        if not self.action and not self.dragging:
            self.expr = expr

    # ------------------------------------------------------------ 点击

    def trigger(self) -> bool:
        if self.dragging:
            return False
        if self.t - self.last_click < 0.18:
            return False
        self.last_click = self.t

        # 2.5 秒内连点第 5 次才恼
        if self._clicks and self.t - self._clicks[-1] > POKE_WINDOW:
            self._clicks = []
        self._clicks.append(self.t)
        if len(self._clicks) >= POKE_LIMIT:
            self._clicks = []
            self.action = "annoyed"
            self.action_start = self.t
            self.action_duration = DURATION["annoyed"]
            self.expr = "01_angry"
            self.happy = 0.0
            return True

        self.action = random.choice(ACTIONS)
        self.action_start = self.t
        self.action_duration = DURATION[self.action]
        self.happy = 1.0
        self.expr = random.choice(ACTION_EXPR.get(self.action, (self.idle_expr,)))

        if self.action == "love":
            self._spawn_hearts()
        elif self.action == "splash":
            self._spawn_drops()
        elif self.action == "spin":
            self._spawn_sparks()
        return True

    # ------------------------------------------------------------ 拖拽

    def begin_drag(self) -> None:
        self.dragging = True
        self.drag_speed = 0.0
        self.action = None
        self.expr = "07_stumble"

    def drag_step(self, dx: float, dy: float, dt: float) -> None:
        if not self.dragging:
            return
        speed = math.hypot(dx, dy) / max(dt, 0.008)
        self.drag_speed = self.drag_speed * 0.55 + speed * 0.45
        if self.drag_speed < DRAG_SLOW:
            self.expr = "07_stumble"       # 小碎步被拽着走
        elif self.drag_speed < DRAG_FAST:
            self.expr = "08_tumble"        # 踉跄
        else:
            self.expr = "09_faceplant"     # 直接拖飞

    def end_drag(self) -> None:
        if not self.dragging:
            return
        self.meal = False
        self.meal_start = 0.0
        self.dragging = False
        # 松手时按刚才的拖动速度决定摔成什么样
        if self.drag_speed < DRAG_SLOW:
            self.expr = "10_sit"           # 慢慢停下，坐地上
        elif self.drag_speed < DRAG_FAST:
            self.expr = "11_hurt_sit"      # 摔懵了
        else:
            self.expr = "12_cry"           # 摔疼了
        self.action = "recover"
        self.action_start = self.t
        self.action_duration = DURATION["recover"]

    def set_meal(self, active: bool) -> None:
        """午休时段：开始吃饭。"""
        if active and not self.meal:
            self.meal_start = self.t
        self.meal = active

    def _meal_frame(self) -> str:
        elapsed = self.t - self.meal_start
        if elapsed < MEAL_SWITCH:
            return MEAL_EARLY[int(elapsed / MEAL_EARLY_STEP) % len(MEAL_EARLY)]
        idx = int((elapsed - MEAL_SWITCH) / MEAL_LATE_STEP) % len(MEAL_LATE)
        return MEAL_LATE[idx]

    def pat(self) -> None:
        """鼠标碰到形象：被摸头，先一激灵再害羞/开心。"""
        if self.action not in (None, "pat"):
            return
        if self.t - getattr(self, "_last_pat", -10.0) < 0.6:
            return
        self._last_pat = self.t
        self._pat_expr = random.choice(PAT_REACTIONS)
        self.action = "pat"
        self.action_start = self.t
        self.action_duration = PAT_WINDOW
        self.expr = "25_shock"

    def lift(self) -> None:
        """长按 2 秒：被人拎起来，先炸毛再闹脾气。"""
        self.action = "lift"
        self.action_start = self.t
        self.action_duration = LIFT_DURATION
        self._lift_ending = random.choice(LIFT_ENDINGS)
        self.expr = "19_shock"
        self._clicks = []

    def react(self, kind: str) -> None:
        """外部事件让角色做个反应：sit=起身提醒，off=下班。"""
        if kind == "sit":
            self.action = "wave"
            self.action_start = self.t
            self.action_duration = DURATION["wave"]
            self.expr = "05_wave"
        elif kind == "off":
            self.action = "hop"
            self.action_start = self.t
            self.action_duration = DURATION["hop"] * 1.6
            self.expr = "06_laugh"

    def _progress(self) -> float:
        if not self.action:
            return 0.0
        return max(0.0, min(1.0, (self.t - self.action_start) / self.action_duration))

    # ------------------------------------------------------------ 粒子

    def _spawn_hearts(self) -> None:
        for _ in range(7):
            self.particles.append(
                Particle(
                    x=random.uniform(-42, 42),
                    y=random.uniform(-56, -20),
                    vx=random.uniform(-16, 16),
                    vy=random.uniform(-50, -28),
                    life=1.1,
                    total=1.1,
                    kind="heart",
                    size=random.uniform(7, 11),
                )
            )

    def _spawn_drops(self) -> None:
        for _ in range(12):
            self.particles.append(
                Particle(
                    x=random.uniform(-4, 4),
                    y=-72,
                    vx=random.uniform(-26, 26),
                    vy=random.uniform(-92, -58),
                    life=1.3,
                    total=1.3,
                    kind="drop",
                    size=random.uniform(2.6, 5.2),
                )
            )

    def _spawn_sparks(self) -> None:
        for _ in range(6):
            angle = random.uniform(0, math.tau)
            radius = random.uniform(52, 70)
            self.particles.append(
                Particle(
                    x=math.cos(angle) * radius,
                    y=math.sin(angle) * radius,
                    vx=math.cos(angle) * 30,
                    vy=math.sin(angle) * 30,
                    life=0.7,
                    total=0.7,
                    kind="spark",
                    size=random.uniform(2.6, 4.6),
                    spin=random.uniform(-6, 6),
                )
            )

    # ------------------------------------------------------------ 绘制

    def draw(self, painter: QPainter, cx: float, cy: float) -> None:
        progress = self._progress()
        rot = 0.0
        sx = 1.0
        sy = 1.0
        dy = 0.0

        breathe = 1 + 0.014 * math.sin(self.t * 2.0)
        hover = 1.04 if (self.hover and not self.dragging) else 1.0
        sx *= breathe * hover
        sy *= breathe * hover
        dy += 1.6 * math.sin(self.t * 1.6)

        if self.dragging:
            # 被拖着走时东倒西歪
            intensity = min(1.0, self.drag_speed / 900.0)
            rot = 7 * intensity * math.sin(self.t * 19)
            dy -= 3 * intensity * abs(math.sin(self.t * 13))
        elif self.action == "hop":
            lift = math.sin(math.pi * progress)
            dy -= 26 * lift
            sy *= 1 + 0.05 * lift
            sx *= 1 - 0.04 * lift
            if progress > 0.86:
                squash = (progress - 0.86) / 0.14
                sy *= 1 - 0.08 * math.sin(math.pi * squash)
                sx *= 1 + 0.07 * math.sin(math.pi * squash)
        elif self.action == "wiggle":
            rot = 9 * math.sin(progress * math.pi * 4) * (1 - progress)
        elif self.action == "spin":
            rot = 360 * (3 * progress * progress - 2 * progress * progress * progress)
        elif self.action == "squish":
            squash = math.sin(math.pi * progress)
            sy *= 1 - 0.18 * squash
            sx *= 1 + 0.13 * squash
            dy += 5 * squash
        elif self.action == "wink":
            rot = 6 * math.sin(math.pi * progress)
        elif self.action == "love":
            sy *= 1 + 0.035 * math.sin(math.pi * progress)
        elif self.action == "splash":
            dy -= 5 * math.sin(math.pi * progress)
        elif self.action == "pat":
            dy -= 2.2 * math.sin(progress * math.pi)
            sy *= 1 + 0.025 * math.sin(progress * math.pi * 4)
        elif self.action == "lift":
            rise = min(1.0, progress * 3.2)
            dy -= 28 * rise
            if 0.25 < progress < 0.53:
                rot = 8 * math.sin(self.t * 21)      # 挣扎
            else:
                rot = 3.5 * math.sin(self.t * 6)     # 被吊着轻晃
        elif self.action == "annoyed":
            rot = 5 * math.sin(progress * math.pi * 10) * (1 - progress)
            dy -= 3 * math.sin(math.pi * progress)
        elif self.action == "wave":
            dy -= 2.5 * abs(math.sin(progress * math.pi * 2))
        elif self.action == "recover":
            # 摔在地上先抖一下
            if progress < 0.35:
                k = 1 - progress / 0.35
                rot = 3 * k * math.sin(self.t * 16)
        elif self.action == "stand_up":
            # 站起来的小弹跳
            k = math.sin(math.pi * progress)
            sy *= 0.9 + 0.1 * k
            sx *= 1.05 - 0.05 * k
            dy += 4 * (1 - k)
        elif self.action == "dizzy":
            rot = 7 * math.sin(progress * math.pi * 6) * (1 - progress * 0.5)

        self._draw_particles(painter, cx)

        pix = self.frames.get(self.expr)
        if pix is None or pix.isNull():
            return

        box = CHAR_BOX
        center_y = CHAR_TOP + box / 2 + dy + EXPR_OFFSET.get(self.expr, 0.0)
        target = QRectF(
            cx - box * sx / 2,
            center_y - box * sy / 2,
            box * sx,
            box * sy,
        )

        painter.save()
        if rot:
            painter.translate(cx, center_y)
            painter.rotate(rot)
            painter.translate(-cx, -center_y)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(target, pix, QRectF(pix.rect()))
        painter.restore()

    def _draw_particles(self, painter: QPainter, cx: float) -> None:
        base = CHAR_TOP + CHAR_BOX / 2
        for p in self.particles:
            ratio = max(0.0, p.life / p.total)
            if p.kind == "heart":
                painter.setBrush(QColor(255, 122, 158, int(235 * ratio)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.save()
                painter.translate(cx + p.x, base + p.y)
                painter.scale(ratio * 1.1, ratio * 1.1)
                painter.drawPath(_heart_path(p.size))
                painter.restore()
            elif p.kind == "drop":
                painter.setBrush(QColor(150, 205, 250, int(220 * ratio)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(
                    QPointF(cx + p.x, base + p.y), p.size * ratio, p.size * ratio
                )
            else:
                painter.setBrush(QColor(255, 228, 140, int(230 * ratio)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.save()
                painter.translate(cx + p.x, base + p.y)
                painter.rotate(p.spin * (1 - ratio) * 40)
                painter.drawPath(_heart_path(p.size * ratio))
                painter.restore()
