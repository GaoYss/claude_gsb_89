"""隐患登记与整改跟踪 Schema。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from app.models.enums import (
    HazardSeverity,
    HazardSource,
    HazardStatus,
    RectificationAction,
    ReopenStatus,
    StructurePart,
)
from app.schemas.common import is_overdue
from app.schemas.reservoir import ReservoirBrief


class HazardCreate(BaseModel):
    reservoir_id: int
    inspection_id: int | None = Field(default=None, description="来源巡查记录，可空")
    title: str = Field(min_length=1, max_length=160, description="隐患标题")
    category: StructurePart = Field(description="隐患类别（部位）")
    severity: HazardSeverity = Field(default=HazardSeverity.GENERAL)
    source: HazardSource = Field(default=HazardSource.INSPECTION)
    discovered_on: date | None = Field(default=None, description="发现日期，缺省为今天")
    discoverer: str | None = Field(default=None, max_length=64)
    deadline: date | None = Field(default=None, description="整改期限")
    assignee: str | None = Field(default=None, max_length=64, description="整改责任人")
    description: str | None = Field(default=None, description="隐患描述")
    plan: str | None = Field(default=None, description="整改方案 / 要求")


class HazardUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    category: StructurePart | None = None
    severity: HazardSeverity | None = None
    source: HazardSource | None = None
    discovered_on: date | None = None
    discoverer: str | None = Field(default=None, max_length=64)
    deadline: date | None = None
    assignee: str | None = Field(default=None, max_length=64)
    description: str | None = None
    plan: str | None = None
    inspection_id: int | None = None
    status: HazardStatus | None = Field(
        default=None, description="如需变更状态，请走 /transition 接口以留痕"
    )


class HazardRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    code: str
    reservoir_id: int
    inspection_id: int | None = None
    title: str
    category: StructurePart
    severity: HazardSeverity
    status: HazardStatus
    source: HazardSource
    discovered_on: date
    discoverer: str | None = None
    deadline: date | None = None
    assignee: str | None = None
    description: str | None = None
    plan: str | None = None
    closed_on: date | None = None
    reopen_count: int = Field(default=0, description="销号重启次数，0 表示首轮整改中")
    created_at: datetime
    updated_at: datetime

    reservoir: ReservoirBrief | None = None

    @computed_field(description="是否逾期（未销号且已过整改期限）")
    @property
    def is_overdue(self) -> bool:
        return is_overdue(self.deadline, self.status.value)


class HazardRectificationCreate(BaseModel):
    action: RectificationAction = Field(default=RectificationAction.PROGRESS, description="记录类型")
    content: str = Field(min_length=1, description="记录内容")
    operator: str | None = Field(default=None, max_length=64, description="记录人")
    recorded_at: datetime | None = Field(default=None, description="记录时间，缺省为当前时间")


class HazardRectificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hazard_id: int
    action: RectificationAction
    content: str
    operator: str | None = None
    status_from: HazardStatus | None = None
    status_to: HazardStatus | None = None
    round_no: int = 1
    recorded_at: datetime


class HazardTransitionRequest(BaseModel):
    """状态流转请求。"""

    target_status: HazardStatus
    content: str | None = Field(default=None, description="流转说明，会写入整改跟踪流水")
    operator: str | None = Field(default=None, max_length=64, description="操作人")


class HazardTransitionOption(BaseModel):
    """可执行的状态流转（前端据此渲染按钮）。"""

    target_status: HazardStatus
    label: str
    require_content: bool = False


class HazardReopenCreate(BaseModel):
    """已销号隐患重启申请：说明同类问题再次出现的原因。"""

    reason: str = Field(min_length=5, max_length=1000, description="重启原因：同类问题再次出现的情况")
    applicant: str | None = Field(default=None, max_length=64, description="申请人")


class HazardReopenReview(BaseModel):
    """重启申请的确认 / 驳回；确认必须填写重启依据。"""

    decision: str = Field(description="confirmed=确认重启，rejected=驳回申请")
    evidence: str | None = Field(
        default=None, min_length=5, max_length=1000, description="重启依据（现场复核 / 佐证材料）"
    )
    confirmer: str | None = Field(default=None, max_length=64, description="确认人")
    review_comment: str | None = Field(default=None, max_length=1000, description="确认 / 驳回意见")
    deadline: date | None = Field(
        default=None, description="确认重启时可一并指定新一轮整改期限"
    )

    @field_validator("decision")
    @classmethod
    def _check_decision(cls, value: str) -> str:
        normalized = (value or "").strip().lower()
        if normalized not in (ReopenStatus.CONFIRMED.value, ReopenStatus.REJECTED.value):
            raise ValueError("decision 只能是 confirmed 或 rejected")
        return normalized

    @property
    def confirmed(self) -> bool:
        return self.decision == ReopenStatus.CONFIRMED.value


class HazardReopenRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hazard_id: int
    round_no: int
    status: ReopenStatus
    reason: str
    evidence: str | None = None
    applicant: str | None = None
    applied_at: datetime
    confirmer: str | None = None
    confirmed_at: datetime | None = None
    review_comment: str | None = None
    previous_closed_on: date | None = None
    hazard: HazardRead | None = None


class HazardDetail(HazardRead):
    """隐患详情：附带整改跟踪流水与重启申请记录。"""

    rectifications: list[HazardRectificationRead] = Field(default_factory=list)
    reopen_requests: list[HazardReopenRead] = Field(default_factory=list)
