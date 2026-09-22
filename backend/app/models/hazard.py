"""隐患登记与整改跟踪模型。"""

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, now_local
from app.models.enums import HazardSeverity, HazardStatus, ReopenStatus

if TYPE_CHECKING:
    from app.models.inspection import Inspection
    from app.models.reservoir import Reservoir


class Hazard(TimestampMixin, Base):
    """隐患（问题）台账。"""

    __tablename__ = "hazard"
    __table_args__ = (
        Index("ix_hazard_reservoir_status", "reservoir_id", "status"),
        Index("ix_hazard_deadline", "deadline"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True, comment="隐患编号")
    reservoir_id: Mapped[int] = mapped_column(
        ForeignKey("reservoir.id", ondelete="CASCADE"), index=True
    )
    inspection_id: Mapped[int | None] = mapped_column(
        ForeignKey("inspection.id", ondelete="SET NULL"), index=True, comment="来源巡查记录"
    )
    title: Mapped[str] = mapped_column(String(160), comment="隐患标题")
    category: Mapped[str] = mapped_column(String(24), index=True, comment="隐患类别（部位）")
    severity: Mapped[str] = mapped_column(
        String(16), default=HazardSeverity.GENERAL.value, index=True, comment="隐患等级"
    )
    status: Mapped[str] = mapped_column(
        String(24), default=HazardStatus.REGISTERED.value, index=True, comment="整改状态"
    )
    source: Mapped[str] = mapped_column(String(24), default="inspection", comment="隐患来源")
    discovered_on: Mapped[date] = mapped_column(Date, index=True, comment="发现日期")
    discoverer: Mapped[str | None] = mapped_column(String(64), comment="发现人")
    deadline: Mapped[date | None] = mapped_column(Date, comment="整改期限")
    assignee: Mapped[str | None] = mapped_column(String(64), comment="整改责任人")
    description: Mapped[str | None] = mapped_column(Text, comment="隐患描述")
    plan: Mapped[str | None] = mapped_column(Text, comment="整改方案 / 要求")
    closed_on: Mapped[date | None] = mapped_column(Date, comment="本次销号日期")
    reopen_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", comment="已销号重启次数（0 表示首轮整改）"
    )

    reservoir: Mapped["Reservoir"] = relationship(back_populates="hazards")
    inspection: Mapped["Inspection | None"] = relationship(back_populates="hazards")
    rectifications: Mapped[list["HazardRectification"]] = relationship(
        back_populates="hazard",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="HazardRectification.recorded_at",
    )
    reopen_requests: Mapped[list["HazardReopen"]] = relationship(
        back_populates="hazard",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="HazardReopen.id",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Hazard {self.code} status={self.status}>"


class HazardRectification(TimestampMixin, Base):
    """整改跟踪流水（措施、进展、验收、销号）。"""

    __tablename__ = "hazard_rectification"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hazard_id: Mapped[int] = mapped_column(
        ForeignKey("hazard.id", ondelete="CASCADE"), index=True
    )
    action: Mapped[str] = mapped_column(String(24), comment="记录类型")
    content: Mapped[str] = mapped_column(Text, comment="记录内容")
    operator: Mapped[str | None] = mapped_column(String(64), comment="记录人")
    status_from: Mapped[str | None] = mapped_column(String(24), comment="变更前状态")
    status_to: Mapped[str | None] = mapped_column(String(24), comment="变更后状态")
    round_no: Mapped[int] = mapped_column(
        Integer, default=1, server_default="1", index=True, comment="所属整改轮次（重启后递增）"
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_local, index=True, comment="记录时间"
    )

    hazard: Mapped["Hazard"] = relationship(back_populates="rectifications")


class HazardReopen(TimestampMixin, Base):
    """已销号隐患的重启申请与确认记录。

    - 申请阶段只登记「同类问题再次出现」的重启原因，隐患仍保持已销号；
    - 确认阶段必须填写重启依据（复核情况 / 佐证材料），确认后隐患才重新进入
      「待整改」，开启新一轮整改任务，原整改流水全部保留；
    - 同一条隐患同时只允许存在一条待确认申请，重复发起不会产生多条整改任务。
    """

    __tablename__ = "hazard_reopen"
    __table_args__ = (
        Index("ix_hazard_reopen_hazard", "hazard_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hazard_id: Mapped[int] = mapped_column(
        ForeignKey("hazard.id", ondelete="CASCADE"), index=True
    )
    round_no: Mapped[int] = mapped_column(Integer, comment="确认重启后进入的整改轮次")
    status: Mapped[str] = mapped_column(
        String(16),
        default=ReopenStatus.PENDING.value,
        server_default=ReopenStatus.PENDING.value,
        comment="确认状态：待确认 / 已确认 / 已驳回",
    )
    reason: Mapped[str] = mapped_column(Text, comment="重启原因（同类问题再次出现的情况）")
    evidence: Mapped[str | None] = mapped_column(Text, comment="重启依据（现场复核 / 佐证材料）")
    applicant: Mapped[str | None] = mapped_column(String(64), comment="申请人")
    applied_at: Mapped[datetime] = mapped_column(
        DateTime, default=now_local, comment="申请时间"
    )
    confirmer: Mapped[str | None] = mapped_column(String(64), comment="确认人")
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, comment="确认 / 驳回时间")
    review_comment: Mapped[str | None] = mapped_column(Text, comment="确认 / 驳回意见")
    previous_closed_on: Mapped[date | None] = mapped_column(
        Date, comment="本次重启前的销号日期快照"
    )

    hazard: Mapped["Hazard"] = relationship(back_populates="reopen_requests")


class MonthlyReport(TimestampMixin, Base):
    """隐患整改月报快照。

    月报一经生成即为固化快照：之后隐患被销号重启、状态变化都不会回写已生成的
    月报，保证历史月报与当时口径一致。重新生成同一期月报需显式覆盖。
    """

    __tablename__ = "monthly_report"
    __table_args__ = (UniqueConstraint("period", name="uq_monthly_report_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period: Mapped[str] = mapped_column(String(7), unique=True, index=True, comment="所属月份 YYYY-MM")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=now_local, comment="生成时间")
    generated_by: Mapped[str | None] = mapped_column(String(64), comment="生成人")
    remark: Mapped[str | None] = mapped_column(Text, comment="备注")
    data: Mapped[dict] = mapped_column(JSON, comment="月报统计快照（生成时刻口径）")
