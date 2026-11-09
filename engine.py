"""时间引擎：把「作息配置 + 当前时间」算成界面状态与提醒事件。

设计要点：
- 用「跨点检测」(prev < 目标时刻 <= now) 触发提醒，避免启动时补发历史提醒，
  同时天然支持休眠唤醒后的补偿。
- 久坐计时以「上次起身时刻」为锚点，午休 / 暂停 / 非工作日时不断前移锚点。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import List, Optional

PRE, WORK, OFF, REST = "pre", "work", "off", "rest"


def parse_time(value, fallback: str = "18:00") -> time:
    try:
        hour, minute = str(value).split(":")[:2]
        return time(int(hour), int(minute))
    except Exception:
        hour, minute = fallback.split(":")
        return time(int(hour), int(minute))


def fmt_hms(seconds: int) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


@dataclass
class Snapshot:
    now: datetime = field(default_factory=datetime.now)
    phase: str = WORK
    is_workday: bool = True
    seconds_left: int = 0        # 距下班秒数，负数表示已超时
    day_progress: float = 0.0    # 0~1
    sit_minutes: float = 0.0
    sit_target: int = 45
    sit_active: bool = True      # 当前是否在计时（午休 / 暂停时为 False）
    sit_reason: str = "ok"       # ok | lunch | paused | rest | off
    paused: bool = False
    report_due: bool = False     # 今天是本周最后一个工作日且已过提醒时间
    drink_state: str = "empty"   # empty | half | full
    drink_cups: int = 0          # 今天喝了几杯
    drink_left: int = 0          # 距下次喝水还有几分钟


@dataclass
class Event:
    kind: str                    # pre_off | off_work | off_again | sit | weekly_report
    minutes: int = 0
    hard: bool = False
    monthly: bool = False        # 这次是否连月报一起提醒


class Engine:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._day: Optional[date] = None
        self._last = datetime.now()
        self._report_day = None
        self.report_again_at = None
        self.drink_start = datetime.now()
        self.drink_alerts = 0
        self.drink_last_alert = None
        self.sit_start = datetime.now()
        self.sit_alerts = 0
        self.sit_last_alert: Optional[datetime] = None
        self.sit_alert_gap = max(3, int(cfg["sit_snooze"] or 5))
        self.pause_until: Optional[datetime] = None
        self.off_again_at: Optional[datetime] = None
        self.snapshot = Snapshot()

    # ------------------------------------------------------------ 对外动作

    def stand_up(self) -> None:
        """用户表示已经起身，重新计时。"""
        self.sit_start = datetime.now()
        self.sit_alerts = 0
        self.sit_last_alert = None

    @staticmethod
    def _is_month_last_workday(now: datetime, work_days: list[int]) -> bool:
        """今天是不是本月最后一个工作日（后面没有工作日了）。"""
        import calendar

        last_day = calendar.monthrange(now.year, now.month)[1]
        for day in range(last_day, now.day - 1, -1):
            candidate = now.replace(day=day).date()
            if candidate.weekday() in work_days:
                return candidate == now.date()
        return False

    def mark_report_done(self) -> None:
        """点了「写过了」：今天不再提醒（写进配置，重启也不提醒）。"""
        self.cfg["report_done_date"] = datetime.now().date().isoformat()
        self.cfg.save()

    def snooze_drink(self, minutes: int = 10) -> None:
        """「10 分钟后」：重置计数，过一会儿再催。"""
        self.drink_last_alert = datetime.now()
        self.drink_alerts = 0

    def drink_done(self) -> None:
        """点了水杯：记一杯，从头计时。"""
        self.drink_start = datetime.now()
        self.drink_alerts = 0
        self.drink_last_alert = None
        today = datetime.now().date().isoformat()
        cups = int(self.cfg["drink_cups"] or 0)
        if str(self.cfg["drink_cups_date"] or "") != today:
            cups = 0
        self.cfg["drink_cups"] = cups + 1
        self.cfg["drink_cups_date"] = today
        self.cfg.save()

    def snooze_report(self, minutes: int = 10) -> None:
        """周报提醒「10 分钟后」：到点再催一次。"""
        self.report_again_at = datetime.now() + timedelta(minutes=max(1, minutes))

    def snooze_sit(self) -> None:
        """稍后再说：不休止计时，只是延后下一次打扰。"""
        minutes = max(1, int(self.cfg["sit_snooze"] or 5))
        self.sit_last_alert = datetime.now()
        self.sit_alert_gap = minutes
        if self.sit_alerts >= 3:
            self.sit_alerts = 1

    def pause_sit(self, minutes: int = 30) -> None:
        self.pause_until = datetime.now() + timedelta(minutes=minutes)
        self.sit_start = self.pause_until
        self.sit_alerts = 0
        self.sit_last_alert = None

    def resume_sit(self) -> None:
        self.pause_until = None
        self.stand_up()

    def snooze_off(self, minutes: int = 10) -> None:
        self.off_again_at = datetime.now() + timedelta(minutes=minutes)

    # ------------------------------------------------------------ 主循环

    def tick(self, now: datetime) -> List[Event]:
        events: List[Event] = []

        if self._day != now.date():
            self._day = now.date()
            self.sit_start = now
            self.sit_alerts = 0
            self.sit_last_alert = None
            self.off_again_at = None

        prev = self._last
        self._last = now

        workday = now.weekday() in (self.cfg["work_days"] or [])
        off_t = parse_time(self.cfg["off_work"], "18:00")
        start_t = parse_time(self.cfg["start_work"], "09:30")
        off_dt = datetime.combine(now.date(), off_t)
        start_dt = datetime.combine(now.date(), start_t)
        pre_min = max(0, int(self.cfg["pre_alert_min"] or 0))

        # ---- 下班提醒 ----
        if workday:
            pre_dt = off_dt - timedelta(minutes=pre_min)
            if pre_min and prev < pre_dt <= now and now < off_dt:
                events.append(Event("pre_off", minutes=pre_min))
            if prev < off_dt <= now:
                events.append(Event("off_work"))

        if self.off_again_at and now >= self.off_again_at:
            self.off_again_at = None
            events.append(Event("off_again"))

        if self.report_again_at and now >= self.report_again_at:
            self.report_again_at = None
            events.append(Event("weekly_report"))

        # 本周最后一个工作日到点提醒写周报
        report_due = False
        if workday and self.cfg["weekly_report_enabled"]:
            days = list(self.cfg["work_days"] or [])
            at = parse_time(self.cfg["weekly_report_time"], "17:40")
            trigger = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
            if days and now.weekday() == max(days):
                report_due = now >= trigger
                # 过了提醒时间就补一次（包括 17:40 之后才开机的场景）
                done_today = self.cfg["report_done_date"] == now.date().isoformat()
                if now >= trigger and not done_today and self._report_day != now.date():
                    self._report_day = now.date()
                    monthly = self._is_month_last_workday(now, days)
                    events.append(Event("weekly_report", monthly=monthly))

        # ---- 阶段判定 ----
        if not workday:
            phase = REST
        elif now >= off_dt:
            phase = OFF
        elif pre_min and now >= off_dt - timedelta(minutes=pre_min):
            phase = PRE
        else:
            phase = WORK

        span = (off_dt - start_dt).total_seconds() or 1.0
        progress = (now - start_dt).total_seconds() / span

        # ---- 久坐计时 ----
        paused = bool(self.pause_until and now < self.pause_until)
        if self.pause_until and not paused:
            self.pause_until = None

        lunch = self._in_lunch(now)
        if not workday:
            sit_reason = "rest"
        elif now < start_dt:
            sit_reason = "before"      # 还没到上班时间，不计时
        elif now >= off_dt:
            sit_reason = "after"       # 已经下班，不计时
        elif not self.cfg["sit_enabled"]:
            sit_reason = "off"
        elif paused:
            sit_reason = "paused"
        elif lunch:
            sit_reason = "lunch"
        else:
            sit_reason = "ok"

        sit_active = sit_reason == "ok"

        if not sit_active:
            self.sit_start = now
            self.sit_alerts = 0
            self.sit_last_alert = None
            sit_minutes = 0.0
        else:
            sit_minutes = max(0.0, (now - self.sit_start).total_seconds() / 60.0)
            target = max(5, int(self.cfg["sit_interval"] or 45))
            # 前三次按用户选择的间隔催，之后拉长到 30 分钟一次，最多七次
            if self.sit_alerts < 3:
                gap = max(3, int(getattr(self, "sit_alert_gap", self.cfg["sit_snooze"] or 5)))
            else:
                gap = 30
            if sit_minutes >= target and self.sit_alerts < 7:
                due = (
                    self.sit_last_alert is None
                    or (now - self.sit_last_alert) >= timedelta(minutes=gap)
                )
                if due:
                    self.sit_last_alert = now
                    self.sit_alerts += 1
                    events.append(
                        Event("sit", minutes=int(sit_minutes), hard=self.sit_alerts >= 3)
                    )

        # ---- 喝水 ----
        drink_state = "empty"
        drink_left = 0
        cups = int(self.cfg["drink_cups"] or 0)
        if str(self.cfg["drink_cups_date"] or "") != now.date().isoformat():
            cups = 0
        if self.cfg["drink_enabled"] and sit_active:
            interval = max(15, int(self.cfg["drink_interval"] or 60))
            elapsed = max(0.0, (now - self.drink_start).total_seconds() / 60.0)
            ratio = elapsed / interval
            drink_left = max(0, int(round(interval - elapsed)))
            if ratio >= 1.0:
                drink_state = "full"
                due = (
                    self.drink_last_alert is None
                    or (now - self.drink_last_alert).total_seconds() >= 600
                )
                if due and self.drink_alerts < 3:
                    self.drink_alerts += 1
                    self.drink_last_alert = now
                    events.append(Event("drink"))
            elif ratio >= 0.75:
                drink_state = "half"
        else:
            self.drink_start = now
            self.drink_alerts = 0
            self.drink_last_alert = None

        self.snapshot = Snapshot(
            now=now,
            phase=phase,
            is_workday=workday,
            seconds_left=int((off_dt - now).total_seconds()),
            day_progress=max(0.0, min(1.0, progress)),
            sit_minutes=sit_minutes,
            sit_target=int(self.cfg["sit_interval"] or 45),
            sit_active=sit_active,
            sit_reason=sit_reason,
            paused=paused,
            report_due=report_due,
            drink_state=drink_state,
            drink_cups=cups,
            drink_left=drink_left,
        )
        return events

    # ------------------------------------------------------------ 内部

    def in_lunch(self, now: datetime) -> bool:
        """当前是否在午休时段（供界面层判断）。"""
        return self._in_lunch(now)

    def _in_lunch(self, now: datetime) -> bool:
        if not self.cfg["lunch_enabled"]:
            return False
        a = parse_time(self.cfg["lunch_start"], "12:00")
        b = parse_time(self.cfg["lunch_end"], "13:30")
        t = now.time()
        if a <= b:
            return a <= t < b
        return t >= a or t < b
