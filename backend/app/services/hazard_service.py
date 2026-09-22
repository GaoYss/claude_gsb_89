"""隐患登记与整改跟踪业务逻辑（含状态流转规则、销号重启）。"""

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ConflictError, InvalidOperationError, NotFoundError
from app.db.base import now_local
from app.models import Hazard, HazardRectification, HazardRectificationCycle, Inspection
from app.models.enums import HazardStatus, RectificationAction
from app.schemas.hazard import (
    HazardCreate,
    HazardRectificationCreate,
    HazardReopenRequest,
    HazardTransitionOption,
    HazardTransitionRequest,
    HazardUpdate,
)
from app.services import reservoir_service
from app.services.helpers import enum_to_value, next_code


@dataclass(frozen=True)
class TransitionRule:
    """一条允许的状态流转。"""

    target: HazardStatus
    label: str
    action: RectificationAction
    require_content: bool = False


def _rule(
    target: HazardStatus,
    label: str,
    action: RectificationAction,
    require_content: bool = False,
) -> TransitionRule:
    return TransitionRule(target=target, label=label, action=action, require_content=require_content)


# 隐患整改状态机：待整改 -> 整改中 -> 待验收 -> 已销号
# 已销号为终态，只能通过专用的「申请重启」重新进入待整改（见 reopen_hazard）
TRANSITION_RULES: dict[str, list[TransitionRule]] = {
    HazardStatus.REGISTERED.value: [
        _rule(HazardStatus.RECTIFYING, "开始整改", RectificationAction.MEASURE),
        _rule(
            HazardStatus.CLOSED,
            "直接销号（立行立改）",
            RectificationAction.CLOSE,
            require_content=True,
        ),
    ],
    HazardStatus.RECTIFYING.value: [
        _rule(
            HazardStatus.PENDING_ACCEPTANCE,
            "提交验收",
            RectificationAction.PROGRESS,
            require_content=True,
        ),
        _rule(HazardStatus.CLOSED, "直接销号", RectificationAction.CLOSE, require_content=True),
    ],
    HazardStatus.PENDING_ACCEPTANCE.value: [
        _rule(HazardStatus.CLOSED, "验收通过并销号", RectificationAction.VERIFY),
        _rule(
            HazardStatus.RECTIFYING,
            "验收不通过，退回整改",
            RectificationAction.VERIFY,
            require_content=True,
        ),
    ],
    HazardStatus.CLOSED.value: [],
}


def available_transitions(status: str) -> list[HazardTransitionOption]:
    return [
        HazardTransitionOption(
            target_status=rule.target,
            label=rule.label,
            require_content=rule.require_content,
        )
        for rule in TRANSITION_RULES.get(status, [])
    ]


def _find_rule(current: str, target: str) -> TransitionRule | None:
    for rule in TRANSITION_RULES.get(current, []):
        if rule.target.value == target:
            return rule
    return None


def current_cycle_seq(hazard: Hazard) -> int:
    """隐患当前所处的整改轮次序号（首轮为 1）。"""

    return (hazard.reopen_count or 0) + 1


def _active_cycle(hazard: Hazard) -> HazardRectificationCycle | None:
    """当前在办轮次（closed_on 为空的最后一轮）。"""

    for cycle in reversed(hazard.cycles):
        if cycle.closed_on is None:
            return cycle
    return None


def get_hazard(db: Session, hazard_id: int) -> Hazard:
    stmt = (
        select(Hazard)
        .options(
            selectinload(Hazard.reservoir),
            selectinload(Hazard.rectifications),
            selectinload(Hazard.cycles),
        )
        .where(Hazard.id == hazard_id)
    )
    hazard = db.scalar(stmt)
    if hazard is None:
        raise NotFoundError(f"隐患不存在：id={hazard_id}")
    return hazard


def list_hazards(
    db: Session,
    *,
    reservoir_id: int | None = None,
    inspection_id: int | None = None,
    category: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    source: str | None = None,
    keyword: str | None = None,
    overdue_only: bool = False,
    open_only: bool = False,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Hazard], int]:
    conditions = []
    if reservoir_id:
        conditions.append(Hazard.reservoir_id == reservoir_id)
    if inspection_id:
        conditions.append(Hazard.inspection_id == inspection_id)
    if category:
        conditions.append(Hazard.category == category)
    if severity:
        conditions.append(Hazard.severity == severity)
    if status:
        conditions.append(Hazard.status == status)
    if source:
        conditions.append(Hazard.source == source)
    if open_only:
        conditions.append(Hazard.status != HazardStatus.CLOSED.value)
    if overdue_only:
        conditions.append(
            and_(
                Hazard.status != HazardStatus.CLOSED.value,
                Hazard.deadline.is_not(None),
                Hazard.deadline < date.today(),
            )
        )
    if keyword:
        like = f"%{keyword.strip()}%"
        conditions.append(
            or_(
                Hazard.title.like(like),
                Hazard.code.like(like),
                Hazard.description.like(like),
                Hazard.assignee.like(like),
            )
        )

    total = db.scalar(select(func.count()).select_from(Hazard).where(*conditions)) or 0
    rows = db.scalars(
        select(Hazard)
        .options(selectinload(Hazard.reservoir))
        .where(*conditions)
        .order_by(
            Hazard.status.desc(),
            Hazard.deadline.is_(None),
            Hazard.deadline.asc(),
            Hazard.id.desc(),
        )
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total


def create_hazard(db: Session, payload: HazardCreate) -> Hazard:
    reservoir_service.get_reservoir(db, payload.reservoir_id)
    data = enum_to_value(payload.model_dump())

    inspection_id = data.get("inspection_id")
    if inspection_id:
        inspection = db.get(Inspection, inspection_id)
        if inspection is None:
            raise NotFoundError(f"来源巡查记录不存在：id={inspection_id}")
        if inspection.reservoir_id != data["reservoir_id"]:
            raise InvalidOperationError("来源巡查记录与所选水库不一致，请重新选择")

    discovered_on = data.get("discovered_on") or date.today()
    hazard = Hazard(
        code=next_code(db, Hazard, Hazard.code, prefix="YH", on=discovered_on),
        **{**data, "discovered_on": discovered_on},
    )
    # 登记即生成第 1 轮整改任务，并写一条流水，保证整改跟踪时间轴从发现开始可追溯
    hazard.cycles.append(
        HazardRectificationCycle(
            seq=1,
            started_on=discovered_on,
            deadline=hazard.deadline,
        )
    )
    hazard.rectifications.append(
        HazardRectification(
            cycle_seq=1,
            action=RectificationAction.REGISTER.value,
            content=f"隐患登记：{hazard.title}",
            operator=data.get("discoverer"),
            status_from=None,
            status_to=HazardStatus.REGISTERED.value,
        )
    )
    db.add(hazard)
    db.commit()
    return get_hazard(db, hazard.id)


def update_hazard(db: Session, hazard_id: int, payload: HazardUpdate) -> Hazard:
    hazard = get_hazard(db, hazard_id)

    if payload.status is not None and payload.status.value != hazard.status:
        raise InvalidOperationError(
            "状态变更请使用 POST /api/v1/hazards/{id}/transition 接口，以便记录整改流水"
        )

    data = enum_to_value(payload.model_dump(exclude_unset=True, exclude={"status"}))
    if "inspection_id" in data and data["inspection_id"]:
        inspection = db.get(Inspection, data["inspection_id"])
        if inspection is None:
            raise NotFoundError(f"来源巡查记录不存在：id={data['inspection_id']}")
        if inspection.reservoir_id != hazard.reservoir_id:
            raise InvalidOperationError("来源巡查记录与隐患所属水库不一致")

    for key, value in data.items():
        setattr(hazard, key, value)

    # 在办轮次的期限随主单同步，历史轮次快照不动
    if "deadline" in data:
        cycle = _active_cycle(hazard)
        if cycle is not None:
            cycle.deadline = data["deadline"]

    db.commit()
    return get_hazard(db, hazard_id)


def transition_hazard(db: Session, hazard_id: int, payload: HazardTransitionRequest) -> Hazard:
    """按状态机流转隐患状态，并自动写入整改跟踪流水。"""
    hazard = get_hazard(db, hazard_id)
    target = payload.target_status.value
    rule = _find_rule(hazard.status, target)
    if rule is None:
        if hazard.status == HazardStatus.CLOSED.value:
            raise ConflictError(
                "已销号是终态，不能直接变更状态；如同类问题再次出现，"
                "请使用 POST /hazards/{id}/reopen 申请重启整改"
            )
        raise ConflictError(
            f"不允许从「{HazardStatus.label_of(hazard.status)}」变更为"
            f"「{HazardStatus.label_of(target)}」"
        )

    content = (payload.content or "").strip()
    if rule.require_content and not content:
        raise InvalidOperationError(f"变更为「{rule.label}」需要填写处理说明")

    status_from = hazard.status
    seq = current_cycle_seq(hazard)
    today = date.today()
    hazard.status = target
    if target == HazardStatus.CLOSED.value:
        hazard.closed_on = today
        cycle = _active_cycle(hazard)
        if cycle is not None:
            cycle.closed_on = today
    else:
        hazard.closed_on = None
    hazard.rectifications.append(
        HazardRectification(
            cycle_seq=seq,
            action=rule.action.value,
            content=content or rule.label,
            operator=payload.operator,
            status_from=status_from,
            status_to=target,
        )
    )
    db.commit()
    return get_hazard(db, hazard_id)


def reopen_hazard(db: Session, hazard_id: int, payload: HazardReopenRequest) -> Hazard:
    """已销号隐患申请重启：保留原隐患单与全部历史流水，新增一轮整改任务。

    - 仅「已销号」隐患可以重启；在办隐患重复发起返回 409，
      因此同一条隐患的一次在办周期内只会产生一条新的整改任务；
    - 必须填写重启原因、依据并显式确认；
    - 重启后状态回到「待整改」、销号日期清空，统计上不再计入已销号；
    - 历史轮次保持已闭环且日期不可变，已出具的月报口径不会被重启改写。
    """
    hazard = get_hazard(db, hazard_id)
    if hazard.status != HazardStatus.CLOSED.value:
        raise ConflictError(
            f"隐患当前为「{HazardStatus.label_of(hazard.status)}」状态，只有已销号隐患才能申请重启；"
            "该隐患已存在在办整改任务，请勿重复发起"
        )
    if not payload.confirmed:
        raise InvalidOperationError("重启整改需要勾选确认后才能提交")

    reason = payload.reason.strip()
    basis = payload.basis.strip()
    if not reason:
        raise InvalidOperationError("请填写重启原因")
    if not basis:
        raise InvalidOperationError("请填写重启依据")

    today = date.today()
    new_seq = current_cycle_seq(hazard) + 1
    status_from = hazard.status
    hazard.status = HazardStatus.REGISTERED.value
    hazard.closed_on = None
    hazard.reopen_count = (hazard.reopen_count or 0) + 1
    if payload.deadline is not None:
        hazard.deadline = payload.deadline

    hazard.cycles.append(
        HazardRectificationCycle(
            seq=new_seq,
            started_on=today,
            deadline=hazard.deadline,
            reopen_reason=reason,
            reopen_basis=basis,
            operator=payload.operator,
        )
    )
    hazard.rectifications.append(
        HazardRectification(
            cycle_seq=new_seq,
            action=RectificationAction.REOPEN.value,
            content=f"申请重启整改（第 {new_seq} 轮）。\n重启原因：{reason}\n重启依据：{basis}",
            operator=payload.operator,
            status_from=status_from,
            status_to=HazardStatus.REGISTERED.value,
        )
    )
    db.commit()
    return get_hazard(db, hazard_id)


def add_rectification(
    db: Session, hazard_id: int, payload: HazardRectificationCreate
) -> Hazard:
    """追加整改跟踪记录；记录整改措施时自动从「待整改」进入「整改中」。"""
    hazard = get_hazard(db, hazard_id)
    if hazard.status == HazardStatus.CLOSED.value:
        raise ConflictError("隐患已销号，不能再追加整改记录")
    if payload.action in (RectificationAction.REGISTER, RectificationAction.REOPEN):
        raise InvalidOperationError(
            "「登记发现」「重启整改」记录由系统自动生成，不能手工追加"
        )

    record = HazardRectification(
        cycle_seq=current_cycle_seq(hazard),
        action=payload.action.value,
        content=payload.content,
        operator=payload.operator,
        recorded_at=payload.recorded_at or now_local(),
    )
    if (
        payload.action == RectificationAction.MEASURE
        and hazard.status == HazardStatus.REGISTERED.value
    ):
        record.status_from = HazardStatus.REGISTERED.value
        record.status_to = HazardStatus.RECTIFYING.value
        hazard.status = HazardStatus.RECTIFYING.value

    hazard.rectifications.append(record)
    db.commit()
    return get_hazard(db, hazard_id)


def delete_hazard(db: Session, hazard_id: int) -> None:
    hazard = get_hazard(db, hazard_id)
    db.delete(hazard)
    db.commit()


def overdue_hazard_count(db: Session) -> int:
    stmt = (
        select(func.count())
        .select_from(Hazard)
        .where(
            Hazard.status != HazardStatus.CLOSED.value,
            Hazard.deadline.is_not(None),
            Hazard.deadline < date.today(),
        )
    )
    return db.scalar(stmt) or 0


def _cohort_stats(cycles: list, *, month_start: date | None = None) -> dict:
    """统计一组轮次（cycle）的闭环率与办理时长。

    办理时长只统计已销号轮次（closed_on - started_on）；
    传入 month_start/month_end 时，额外给出当月新开 / 当月销号数，
    闭环率按「截至该月末已开始且已销号」的快照口径计算——
    由于历史轮次的起止日期在重启时不会被修改，任何历史月份反复查询
    都得到相同结果，已出具的月报不会被后续重启改写。
    """
    month_end = None
    if month_start is not None:
        month_end = _month_end(month_start)

    if month_end is None:
        scoped = cycles
    else:
        scoped = [cycle for cycle in cycles if cycle.started_on <= month_end]

    total = len(scoped)
    closed_cycles = [
        cycle
        for cycle in scoped
        if cycle.closed_on is not None and (month_end is None or cycle.closed_on <= month_end)
    ]
    closed = len(closed_cycles)
    open_total = total - closed

    durations = [
        (cycle.closed_on - cycle.started_on).days
        for cycle in closed_cycles
        if cycle.closed_on is not None
    ]
    avg_days = round(sum(durations) / len(durations), 1) if durations else None

    started_in_month = closed_in_month = 0
    if month_start is not None and month_end is not None:
        started_in_month = sum(
            1 for cycle in cycles if month_start <= cycle.started_on <= month_end
        )
        closed_in_month = sum(
            1
            for cycle in cycles
            if cycle.closed_on is not None and month_start <= cycle.closed_on <= month_end
        )

    return {
        "total": total,
        "closed": closed,
        "open": open_total,
        "closure_rate": round(closed / len(scoped), 4) if scoped else 0.0,
        "avg_handling_days": avg_days,
        "started_in_period": started_in_month,
        "closed_in_period": closed_in_month,
    }


def _month_end(month_start: date) -> date:
    if month_start.month == 12:
        return date(month_start.year, 12, 31)
    return date(month_start.year, month_start.month + 1, 1).replace(day=1) - timedelta(days=1)


def rectification_stats(db: Session) -> dict:
    """整改任务统计：首轮与重启后轮次分开计算闭环率 / 办理时长。"""
    cycles = list(db.scalars(select(HazardRectificationCycle)).all())
    return {
        "first": _cohort_stats([cycle for cycle in cycles if cycle.seq == 1]),
        "reopened": _cohort_stats([cycle for cycle in cycles if cycle.seq > 1]),
        "reopen_hazard_count": db.scalar(
            select(func.count())
            .select_from(Hazard)
            .where(Hazard.reopen_count > 0)
        )
        or 0,
    }


def monthly_rectification_stats(db: Session, year: int, month: int) -> dict:
    """指定月份的整改月报（基于不可变的轮次快照，历史月份结果不会随重启变化）。"""
    month_start = date(year, month, 1)
    cycles = list(db.scalars(select(HazardRectificationCycle)).all())
    first = [cycle for cycle in cycles if cycle.seq == 1]
    reopened = [cycle for cycle in cycles if cycle.seq > 1]
    return {
        "year": year,
        "month": month,
        "period": f"{year:04d}-{month:02d}",
        "first": _cohort_stats(first, month_start=month_start),
        "reopened": _cohort_stats(reopened, month_start=month_start),
    }
