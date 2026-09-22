"""整改轮次统计与隐患月报接口。"""

from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.report import (
    MonthlyReportGenerate,
    MonthlyReportRead,
    RectificationStats,
)
from app.services import stats_service

router = APIRouter(prefix="/stats", tags=["统计与月报"])


@router.get(
    "/rectification",
    response_model=RectificationStats,
    summary="整改轮次统计（重启前后办理时长 / 闭环率分开）",
)
def rectification_stats(db: DbSession) -> RectificationStats:
    return stats_service.compute_cycle_stats(db)


@router.get("/monthly-reports", response_model=list[MonthlyReportRead], summary="已生成月报列表")
def list_monthly_reports(db: DbSession) -> list:
    return stats_service.list_monthly_reports(db)


@router.get(
    "/monthly-reports/{period}",
    response_model=MonthlyReportRead,
    summary="查看指定期次月报（读取固化快照，不随当前数据变化）",
)
def get_monthly_report(period: str, db: DbSession) -> MonthlyReportRead:
    return stats_service.get_monthly_report(db, period)


@router.post(
    "/monthly-reports",
    response_model=MonthlyReportRead,
    summary="生成月报快照（已生成的期次默认拒绝覆盖）",
)
def generate_monthly_report(payload: MonthlyReportGenerate, db: DbSession) -> MonthlyReportRead:
    from app.db.base import now_local

    period = payload.period or now_local().strftime("%Y-%m")
    return stats_service.generate_monthly_report(
        db,
        period,
        generated_by=payload.generated_by,
        remark=payload.remark,
        overwrite=payload.overwrite,
    )
