"""整改统计与月报服务。

统计口径：
- 隐患每次销号重启开启一个新的「整改轮次」，首轮为第 1 轮；
- 重启前（首轮）与重启后（第 2 轮及以后）的办理时长、闭环率分别统计；
- 重启后仍在整改的隐患计入「未销号」，不再计入「已销号」；
- 月报为生成时刻的快照，固化在 monthly_report.data 中，之后隐患重启或状态
  变化都不回写历史月报。
"""

from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.base import now_local
from app.models import (
    Hazard,
    HazardRectification,
    HazardReopen,
    MonthlyReport,
)
from app.models.enums import (
    HazardSeverity,
    HazardStatus,
    RectificationAction,
    ReopenStatus,
)
from app.schemas.common import NamedCount
from app.schemas.report import (
    CycleStats,
    MonthlyReportData,
    RectificationStats,
)

CLOSED = HazardStatus.CLOSED.value


def _round_markers(hazard: Hazard) -> dict[int, dict[str, datetime | None]]:
    """提取每个整改轮次的开始 / 销号时间点。

    首轮开始取「登记发现」流水时间；重启轮次开始取「销号重启」流水时间；
    销号时间取该轮最后一条变更到已销号的流水时间。
    """
    markers: dict[int, dict[str, datetime | None]] = {}
    for record in hazard.rectifications:
        round_no = record.round_no or 1
        slot = markers.setdefault(round_no, {"start": None, "close": None})
        if record.action == RectificationAction.REGISTER.value and round_no == 1:
            slot["start"] = record.recorded_at
        elif record.action == RectificationAction.REOPEN.value:
            slot["start"] = record.recorded_at
        if record.status_to == CLOSED:
            slot["close"] = record.recorded_at
    if 1 not in markers:
        markers[1] = {"start": hazard.created_at, "close": None}
    return markers


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def compute_cycle_stats(db: Session) -> RectificationStats:
    """按整改轮次分开统计闭环率与平均办理时长。"""
    hazards = db.scalars(
        select(Hazard).options(selectinload(Hazard.rectifications))
    ).all()

    max_round = max([(h.reopen_count or 0) + 1 for h in hazards] + [1])
    entered = {r: 0 for r in range(1, max_round + 1)}
    in_progress = {r: 0 for r in range(1, max_round + 1)}
    closed_current = {r: 0 for r in range(1, max_round + 1)}
    closed_cycles = {r: 0 for r in range(1, max_round + 1)}
    reopened_after = {r: 0 for r in range(1, max_round + 1)}
    durations: dict[int, list[float]] = {r: [] for r in range(1, max_round + 1)}

    for hazard in hazards:
        current_round = (hazard.reopen_count or 0) + 1
        markers = _round_markers(hazard)
        is_closed_now = hazard.status == CLOSED

        for round_no in range(1, current_round + 1):
            entered[round_no] += 1
            slot = markers.get(round_no, {"start": None, "close": None})
            if slot["close"] is not None:
                closed_cycles[round_no] += 1
                if slot["start"] is not None:
                    days = (slot["close"].date() - slot["start"].date()).days
                    durations[round_no].append(float(max(days, 0)))
                # 该轮销号后又进入了更高轮次，即销号后被重启
                if current_round > round_no:
                    reopened_after[round_no] += 1
            elif round_no == current_round and not is_closed_now:
                in_progress[round_no] += 1
            if is_closed_now and round_no == current_round:
                closed_current[round_no] += 1

    def build(round_no: int) -> CycleStats:
        entered_count = entered.get(round_no, 0)
        closed_now = closed_current.get(round_no, 0)
        return CycleStats(
            scope="first_round" if round_no == 1 else "reopened_round",
            label="首轮整改（重启前）" if round_no == 1 else f"第 {round_no} 轮整改（重启后）",
            entered=entered_count,
            in_progress=in_progress.get(round_no, 0),
            closed_current=closed_now,
            closed_cycles=closed_cycles.get(round_no, 0),
            reopened_after_close=reopened_after.get(round_no, 0),
            closure_rate=round(closed_now / entered_count, 4) if entered_count else 0.0,
            avg_handling_days=_mean(durations.get(round_no, [])),
        )

    round_detail = [build(r) for r in range(1, max_round + 1)]
    reopened_detail = round_detail[1:]

    reopened_entered = sum(item.entered for item in reopened_detail)
    reopened_in_progress = sum(item.in_progress for item in reopened_detail)
    reopened_closed_now = sum(item.closed_current for item in reopened_detail)
    reopened_closed_cycles = sum(item.closed_cycles for item in reopened_detail)
    reopened_after_close = sum(item.reopened_after_close for item in reopened_detail)
    reopened_durations = [
        days for round_no in range(2, max_round + 1) for days in durations.get(round_no, [])
    ]

    first = round_detail[0]
    reopened_summary = CycleStats(
        scope="reopened_round",
        label="重启后整改（第 2 轮及以后合计）",
        entered=reopened_entered,
        in_progress=reopened_in_progress,
        closed_current=reopened_closed_now,
        closed_cycles=reopened_closed_cycles,
        reopened_after_close=reopened_after_close,
        closure_rate=(
            round(reopened_closed_now / reopened_entered, 4) if reopened_entered else 0.0
        ),
        avg_handling_days=_mean(reopened_durations),
    )

    return RectificationStats(
        as_of=date.today(),
        first_round=first,
        reopened_round=reopened_summary,
        round_detail=round_detail,
    )


def _month_range(period: str) -> tuple[datetime, datetime]:
    year, month = (int(part) for part in period.split("-"))
    start = datetime(year, month, 1)
    if month == 12:
        end = datetime(year + 1, 1, 1)
    else:
        end = datetime(year, month + 1, 1)
    return start, end


def _distribution(db: Session, column, enum_cls) -> list[NamedCount]:
    rows = db.execute(select(column, func.count()).select_from(Hazard).group_by(column)).all()
    counts = {value: count for value, count in rows}
    return [
        NamedCount(value=value, label=label, count=counts.get(value, 0))
        for value, label in enum_cls.labels().items()
    ]


def build_monthly_data(db: Session, period: str) -> MonthlyReportData:
    """按指定月份口径组装月报数据（不落库）。"""
    today = date.today()
    start, end = _month_range(period)

    hazard_total = db.scalar(select(func.count()).select_from(Hazard)) or 0
    hazard_open = (
        db.scalar(
            select(func.count()).select_from(Hazard).where(Hazard.status != CLOSED)
        )
        or 0
    )
    hazard_closed = (
        db.scalar(select(func.count()).select_from(Hazard).where(Hazard.status == CLOSED))
        or 0
    )
    hazard_overdue = (
        db.scalar(
            select(func.count())
            .select_from(Hazard)
            .where(
                Hazard.status != CLOSED,
                Hazard.deadline.is_not(None),
                Hazard.deadline < today,
            )
        )
        or 0
    )
    # 销号后重启、当前仍在整改：重启次数大于 0 且当前未销号
    hazard_reopened = (
        db.scalar(
            select(func.count())
            .select_from(Hazard)
            .where(Hazard.reopen_count > 0, Hazard.status != CLOSED)
        )
        or 0
    )

    registered_this_month = (
        db.scalar(
            select(func.count())
            .select_from(Hazard)
            .where(Hazard.discovered_on >= start.date(), Hazard.discovered_on < end.date())
        )
        or 0
    )
    closed_this_month = (
        db.scalar(
            select(func.count())
            .select_from(HazardRectification)
            .where(
                HazardRectification.status_to == CLOSED,
                HazardRectification.recorded_at >= start,
                HazardRectification.recorded_at < end,
            )
        )
        or 0
    )
    reopened_this_month = (
        db.scalar(
            select(func.count())
            .select_from(HazardReopen)
            .where(
                HazardReopen.status == ReopenStatus.CONFIRMED.value,
                HazardReopen.confirmed_at.is_not(None),
                HazardReopen.confirmed_at >= start,
                HazardReopen.confirmed_at < end,
            )
        )
        or 0
    )

    return MonthlyReportData(
        period=period,
        as_of=now_local(),
        hazard_total=hazard_total,
        hazard_open=hazard_open,
        hazard_closed=hazard_closed,
        hazard_overdue=hazard_overdue,
        hazard_reopened=hazard_reopened,
        hazard_by_status=_distribution(db, Hazard.status, HazardStatus),
        hazard_by_severity=_distribution(db, Hazard.severity, HazardSeverity),
        registered_this_month=registered_this_month,
        closed_this_month=closed_this_month,
        reopened_this_month=reopened_this_month,
        cycle_stats=compute_cycle_stats(db),
    )


def list_monthly_reports(db: Session) -> list[MonthlyReport]:
    return list(
        db.scalars(select(MonthlyReport).order_by(MonthlyReport.period.desc())).all()
    )


def get_monthly_report(db: Session, period: str) -> MonthlyReport:
    report = db.scalar(select(MonthlyReport).where(MonthlyReport.period == period))
    if report is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(f"{period} 月报尚未生成")
    return report


def generate_monthly_report(
    db: Session,
    period: str,
    *,
    generated_by: str | None = None,
    remark: str | None = None,
    overwrite: bool = False,
) -> MonthlyReport:
    """生成（或显式覆盖）指定月份的月报快照。"""
    from app.core.errors import ConflictError

    existing = db.scalar(select(MonthlyReport).where(MonthlyReport.period == period))
    if existing is not None and not overwrite:
        raise ConflictError(
            f"{period} 月报已存在；历史月报不会自动改写，确需重算请显式指定覆盖"
        )

    snapshot = build_monthly_data(db, period)
    # mode="json" 把 date/datetime 转成 ISO 字符串，兼容 SQLite 的 JSON 存储
    payload = snapshot.model_dump(mode="json")
    if existing is not None:
        existing.data = payload
        existing.generated_at = now_local()
        existing.generated_by = generated_by
        existing.remark = remark
        report = existing
    else:
        report = MonthlyReport(
            period=period,
            generated_at=now_local(),
            generated_by=generated_by,
            remark=remark,
            data=payload,
        )
        db.add(report)
    db.commit()
    db.refresh(report)
    return report
