"""总览页接口。"""

from fastapi import APIRouter, Query

from app.api.deps import DbSession
from app.schemas.hazard import MonthlyRectificationStats
from app.schemas.overview import OverviewSummary
from app.services import hazard_service, overview_service

router = APIRouter(prefix="/overview", tags=["总览"])


@router.get("/summary", response_model=OverviewSummary, summary="首页统计与待办")
def get_summary(db: DbSession) -> OverviewSummary:
    return overview_service.build_summary(db)


@router.get(
    "/rectification-monthly",
    response_model=MonthlyRectificationStats,
    summary="整改月报（重启前 / 重启后分开，历史月份快照不可变）",
)
def get_monthly_rectification(
    db: DbSession,
    year: int = Query(ge=2000, le=2100, description="年份"),
    month: int = Query(ge=1, le=12, description="月份 1-12"),
) -> MonthlyRectificationStats:
    return MonthlyRectificationStats(
        **hazard_service.monthly_rectification_stats(db, year, month)
    )

