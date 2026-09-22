"""整改统计与月报 Schema。"""

from datetime import date, datetime

from pydantic import BaseModel, Field

from app.schemas.common import NamedCount


class CycleStats(BaseModel):
    """按整改轮次（重启前 / 重启后）分开统计的闭环指标。"""

    scope: str = Field(description="first_round=首轮整改，reopened_round=重启后整改")
    label: str
    entered: int = Field(description="进入该轮次的整改任务数")
    in_progress: int = Field(description="该轮次仍在整改（未销号）的任务数")
    closed_current: int = Field(description="该轮次销号且此后未再重启的任务数（当前仍闭环）")
    closed_cycles: int = Field(description="该轮次产生过销号的任务数（含销号后又重启的）")
    reopened_after_close: int = Field(description="该轮次销号后又被重启的任务数")
    closure_rate: float = Field(description="闭环率 = closed_current / entered，保留 4 位小数")
    avg_handling_days: float | None = Field(
        default=None, description="该轮次销号任务的平均办理时长（天，开始到销号）"
    )


class RectificationStats(BaseModel):
    """整改轮次统计：重启前后的办理时长与闭环率分开计算。"""

    as_of: date
    first_round: CycleStats
    reopened_round: CycleStats
    round_detail: list[CycleStats] = Field(
        default_factory=list, description="按具体轮次展开：第 1 轮、第 2 轮……"
    )


class MonthlyReportData(BaseModel):
    """月报快照内容（生成时刻的口径，之后不再变化）。"""

    period: str = Field(description="所属月份 YYYY-MM")
    as_of: datetime = Field(description="快照生成时间")
    hazard_total: int = 0
    hazard_open: int = 0
    hazard_closed: int = Field(default=0, description="当前已销号数（重启后的隐患不计入）")
    hazard_overdue: int = 0
    hazard_reopened: int = Field(default=0, description="销号后重启、当前仍在整改的隐患数")
    hazard_by_status: list[NamedCount] = Field(default_factory=list)
    hazard_by_severity: list[NamedCount] = Field(default_factory=list)
    registered_this_month: int = Field(default=0, description="本月新登记隐患数")
    closed_this_month: int = Field(default=0, description="本月销号的整改轮次数量")
    reopened_this_month: int = Field(default=0, description="本月确认重启的次数")
    cycle_stats: RectificationStats | None = None


class MonthlyReportRead(BaseModel):
    """月报元信息 + 固化快照。"""

    id: int
    period: str
    generated_at: datetime
    generated_by: str | None = None
    remark: str | None = None
    data: MonthlyReportData


class MonthlyReportGenerate(BaseModel):
    """生成月报请求。"""

    period: str | None = Field(
        default=None,
        pattern=r"^\d{4}-(0[1-9]|1[0-2])$",
        description="所属月份 YYYY-MM，缺省为当前月",
    )
    generated_by: str | None = Field(default=None, max_length=64)
    remark: str | None = Field(default=None, max_length=500)
    overwrite: bool = Field(
        default=False, description="同期月报已存在时是否覆盖（默认拒绝，避免误改历史月报）"
    )
