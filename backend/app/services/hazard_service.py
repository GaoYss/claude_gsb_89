"""隐患登记与整改跟踪业务逻辑（含状态流转规则）。"""

from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import ConflictError, InvalidOperationError, NotFoundError
from app.db.base import now_local
from app.models import Hazard, HazardRectification, HazardReopen, Inspection
from app.models.enums import HazardStatus, RectificationAction, ReopenStatus
from app.schemas.hazard import (
    HazardCreate,
    HazardReopenCreate,
    HazardReopenReview,
    HazardRectificationCreate,
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


# 隐患整改状态机：待整改 -> 整改中 -> 待验收 -> 已销号（已销号为终态）
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


def get_hazard(db: Session, hazard_id: int) -> Hazard:
    stmt = (
        select(Hazard)
        .execution_options(populate_existing=True)
        .options(
            selectinload(Hazard.reservoir),
            selectinload(Hazard.rectifications),
            selectinload(Hazard.reopen_requests),
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
    # 登记即写一条流水，保证整改跟踪时间轴从发现开始可追溯
    hazard.rectifications.append(
        HazardRectification(
            action=RectificationAction.REGISTER.value,
            content=f"隐患登记：{hazard.title}",
            operator=data.get("discoverer"),
            status_from=None,
            status_to=HazardStatus.REGISTERED.value,
            round_no=1,
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
    db.commit()
    return get_hazard(db, hazard_id)


def _current_round(hazard: Hazard) -> int:
    """隐患当前所处的整改轮次：重启次数 + 1。"""
    return (hazard.reopen_count or 0) + 1


def transition_hazard(db: Session, hazard_id: int, payload: HazardTransitionRequest) -> Hazard:
    """按状态机流转隐患状态，并自动写入整改跟踪流水。"""
    hazard = get_hazard(db, hazard_id)
    target = payload.target_status.value
    rule = _find_rule(hazard.status, target)
    if rule is None:
        raise ConflictError(
            f"不允许从「{HazardStatus.label_of(hazard.status)}」变更为"
            f"「{HazardStatus.label_of(target)}」"
        )

    content = (payload.content or "").strip()
    if rule.require_content and not content:
        raise InvalidOperationError(f"变更为「{rule.label}」需要填写处理说明")

    status_from = hazard.status
    hazard.status = target
    hazard.closed_on = date.today() if target == HazardStatus.CLOSED.value else None
    hazard.rectifications.append(
        HazardRectification(
            action=rule.action.value,
            content=content or rule.label,
            operator=payload.operator,
            status_from=status_from,
            status_to=target,
            round_no=_current_round(hazard),
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
        raise ConflictError("隐患已销号，不能再追加整改记录；如同类问题再次出现，请申请重启")

    if payload.action == RectificationAction.REOPEN:
        raise InvalidOperationError("重启记录由系统在确认重启时自动生成，不能手工追加")

    record = HazardRectification(
        action=payload.action.value,
        content=payload.content,
        operator=payload.operator,
        recorded_at=payload.recorded_at or now_local(),
        round_no=_current_round(hazard),
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


def _pending_reopen(db: Session, hazard_id: int) -> HazardReopen | None:
    return db.scalar(
        select(HazardReopen)
        .where(
            HazardReopen.hazard_id == hazard_id,
            HazardReopen.status == ReopenStatus.PENDING.value,
        )
        .order_by(HazardReopen.id.desc())
    )


def _get_reopen(db: Session, reopen_id: int) -> HazardReopen:
    request = db.scalar(
        select(HazardReopen)
        .options(selectinload(HazardReopen.hazard).selectinload(Hazard.reservoir))
        .where(HazardReopen.id == reopen_id)
    )
    if request is None:
        raise NotFoundError(f"重启申请不存在：id={reopen_id}")
    return request


def apply_reopen(db: Session, hazard_id: int, payload: HazardReopenCreate) -> HazardReopen:
    """对已销号隐患发起重启申请。

    隐患必须处于已销号终态；同一隐患只允许存在一条待确认申请，重复发起返回
    既有申请，不会产生多条整改任务。
    """
    hazard = get_hazard(db, hazard_id)
    if hazard.status != HazardStatus.CLOSED.value:
        raise ConflictError("只有已销号的隐患才能申请重启")

    existing = _pending_reopen(db, hazard_id)
    if existing is not None:
        return existing

    request = HazardReopen(
        hazard_id=hazard_id,
        round_no=_current_round(hazard) + 1,
        status=ReopenStatus.PENDING.value,
        reason=payload.reason.strip(),
        applicant=(payload.applicant or "").strip() or None,
        applied_at=now_local(),
        previous_closed_on=hazard.closed_on,
    )
    # 通过关系挂载，保证同一会话内已加载的集合也能立即看到新申请
    hazard.reopen_requests.append(request)
    db.add(hazard)
    db.commit()
    return _get_reopen(db, request.id)


def review_reopen(
    db: Session, reopen_id: int, payload: HazardReopenReview
) -> tuple[HazardReopen, Hazard | None]:
    """确认 / 驳回重启申请。

    确认时必须填写重启依据；确认后隐患重新进入「待整改」，整改轮次 +1，
    原整改流水保留，并在时间轴写入「销号重启」节点。驳回则隐患维持已销号。
    返回 (申请记录, 重启后的隐患或 None)。
    """
    request = db.get(HazardReopen, reopen_id)
    if request is None:
        raise NotFoundError(f"重启申请不存在：id={reopen_id}")
    if request.status != ReopenStatus.PENDING.value:
        raise ConflictError("该重启申请已处理，不能重复确认")

    hazard = get_hazard(db, request.hazard_id)
    if payload.confirmed:
        if hazard.status != HazardStatus.CLOSED.value:
            raise ConflictError("隐患当前不是已销号状态，不能确认重启")
        evidence = (payload.evidence or "").strip()
        if not evidence:
            raise InvalidOperationError("确认重启必须填写重启依据（现场复核 / 佐证材料）")

        request.status = ReopenStatus.CONFIRMED.value
        request.evidence = evidence
        request.confirmer = (payload.confirmer or "").strip() or None
        request.review_comment = (payload.review_comment or "").strip() or None
        request.confirmed_at = now_local()

        round_no = _current_round(hazard) + 1
        status_from = hazard.status
        hazard.reopen_count = (hazard.reopen_count or 0) + 1
        hazard.status = HazardStatus.REGISTERED.value
        hazard.closed_on = None
        if payload.deadline is not None:
            hazard.deadline = payload.deadline

        content = (
            f"销号重启（第 {round_no} 轮整改）：{request.reason}；重启依据：{evidence}"
        )
        if request.review_comment:
            content += f"；确认意见：{request.review_comment}"
        hazard.rectifications.append(
            HazardRectification(
                action=RectificationAction.REOPEN.value,
                content=content,
                operator=request.confirmer or request.applicant,
                status_from=status_from,
                status_to=HazardStatus.REGISTERED.value,
                round_no=round_no,
                recorded_at=now_local(),
            )
        )
        db.commit()
        return request, get_hazard(db, hazard.id)

    request.status = ReopenStatus.REJECTED.value
    request.confirmer = (payload.confirmer or "").strip() or None
    request.review_comment = (payload.review_comment or "").strip() or None
    request.confirmed_at = now_local()
    db.commit()
    return request, None


def list_reopen_requests(
    db: Session,
    *,
    status: str | None = None,
    hazard_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[HazardReopen], int]:
    conditions = []
    if status:
        conditions.append(HazardReopen.status == status)
    if hazard_id:
        conditions.append(HazardReopen.hazard_id == hazard_id)

    total = db.scalar(select(func.count()).select_from(HazardReopen).where(*conditions)) or 0
    rows = db.scalars(
        select(HazardReopen)
        .options(selectinload(HazardReopen.hazard).selectinload(Hazard.reservoir))
        .where(*conditions)
        .order_by(HazardReopen.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(rows), total


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
