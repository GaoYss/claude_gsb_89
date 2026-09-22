"""隐患登记与整改跟踪 Schema。"""

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.enums import (
    HazardSeverity,
    HazardSource,
    HazardStatus,
    RectificationAction,
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
    reopen_count: int = 0
    created_at: datetime
    updated_at: datetime

    reservoir: ReservoirBrief | None = None

    @computed_field(description="是否逾期（未销号且已过整改期限）")
    @property
    def is_overdue(self) -> bool:
        return is_overdue(self.deadline, self.status.value)

    @computed_field(description="是否可申请重启（仅已销号隐患可重启）")
    @property
    def can_reopen(self) -> bool:
        return self.status == HazardStatus.CLOSED

    @computed_field(description="是否曾被重启过")
    @property
    def is_reopened(self) -> bool:
        return self.reopen_count > 0

    @computed_field(description="当前整改轮次序号（首轮为 1）")
    @property
    def cycle_seq(self) -> int:
        return self.reopen_count + 1


class HazardRectificationCreate(BaseModel):
    action: RectificationAction = Field(default=RectificationAction.PROGRESS, description="记录类型")
    content: str = Field(min_length=1, description="记录内容")
    operator: str | None = Field(default=None, max_length=64, description="记录人")
    recorded_at: datetime | None = Field(default=None, description="记录时间，缺省为当前时间")


class HazardRectificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    hazard_id: int
    cycle_seq: int = 1
    action: RectificationAction
    content: str
    operator: str | None = None
    status_from: HazardStatus | None = None
    status_to: HazardStatus | None = None
    recorded_at: datetime


class HazardCycleRead(BaseModel):
    """整改轮次（一次整改任务）。"""

    model_config = ConfigDict(from_attributes=True)

    seq: int
    started_on: date
    closed_on: date | None = None
    deadline: date | None = None
    reopen_reason: str | None = None
    reopen_basis: str | None = None
    operator: str | None = None

    @computed_field(description="是否为重启产生的轮次")
    @property
    def is_reopen(self) -> bool:
        return self.seq > 1

    @computed_field(description="本轮办理时长（天），在办中按今天累计")
    @property
    def handling_days(self) -> int:
        end = self.closed_on or date.today()
        return max((end - self.started_on).days, 0)


class HazardTransitionRequest(BaseModel):
    """状态流转请求。"""

    target_status: HazardStatus
    content: str | None = Field(default=None, description="流转说明，会写入整改跟踪流水")
    operator: str | None = Field(default=None, max_length=64, description="操作人")


class HazardReopenRequest(BaseModel):
    """已销号隐患申请重启。

    重启必须说明原因与依据并显式确认；同一隐患在办期间重复发起重启不会
    产生第二条整改任务（接口返回 409）。
    """

    reason: str = Field(min_length=2, description="重启原因：同类问题再次出现的情况说明")
    basis: str = Field(min_length=2, description="重启依据：巡查记录、现场复核或上级要求等")
    operator: str | None = Field(default=None, max_length=64, description="申请人")
    deadline: date | None = Field(default=None, description="本轮整改期限，可空")
    confirmed: bool = Field(description="必须显式确认重启")


class HazardTransitionOption(BaseModel):
    """可执行的状态流转（前端据此渲染按钮）。"""

    target_status: HazardStatus
    label: str
    require_content: bool = False


class HazardDetail(HazardRead):
    """隐患详情：附带整改轮次与整改跟踪流水。"""

    cycles: list[HazardCycleRead] = Field(default_factory=list)
    rectifications: list[HazardRectificationRead] = Field(default_factory=list)


class CycleCohortStats(BaseModel):
    """一批整改轮次（首轮 / 重启后）的统计。"""

    total: int = Field(description="纳入统计的轮次（整改任务）总数")
    closed: int = Field(description="已销号轮次数")
    open: int = Field(description="在办轮次数")
    closure_rate: float = Field(description="闭环率，0~1")
    avg_handling_days: float | None = Field(
        default=None, description="平均办理时长（天），仅按已销号轮次计算"
    )
    started_in_period: int = Field(default=0, description="统计期内新开启的轮次数")
    closed_in_period: int = Field(default=0, description="统计期内销号的轮次数")


class RectificationStats(BaseModel):
    """整改任务统计：首轮与重启后轮次分开。"""

    first: CycleCohortStats = Field(description="首次整改（重启前）")
    reopened: CycleCohortStats = Field(description="重启后的整改任务")
    reopen_hazard_count: int = Field(description="曾被重启过的隐患条数")


class MonthlyRectificationStats(BaseModel):
    """指定月份的整改月报快照（历史月份不受后续重启影响）。"""

    year: int
    month: int
    period: str
    first: CycleCohortStats
    reopened: CycleCohortStats

