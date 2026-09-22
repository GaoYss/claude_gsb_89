"""隐患登记与整改跟踪接口。"""

from fastapi import APIRouter, Query, status

from app.api.deps import DbSession, PageParams
from app.models.enums import (
    HazardSeverity,
    HazardSource,
    HazardStatus,
    ReopenStatus,
    StructurePart,
)
from app.schemas.common import Message, Page
from app.schemas.hazard import (
    HazardCreate,
    HazardDetail,
    HazardRead,
    HazardRectificationCreate,
    HazardReopenCreate,
    HazardReopenRead,
    HazardReopenReview,
    HazardTransitionRequest,
    HazardUpdate,
)
from app.services import hazard_service

router = APIRouter(prefix="/hazards", tags=["隐患与整改"])


@router.get("", response_model=Page[HazardRead], summary="分页查询隐患台账")
def list_hazards(
    db: DbSession,
    pagination: PageParams,
    reservoir_id: int | None = Query(default=None, description="按水库过滤"),
    inspection_id: int | None = Query(default=None, description="按来源巡查记录过滤"),
    category: StructurePart | None = Query(default=None, description="隐患类别（部位）"),
    severity: HazardSeverity | None = Query(default=None, description="隐患等级"),
    hazard_status: HazardStatus | None = Query(default=None, alias="status", description="整改状态"),
    source: HazardSource | None = Query(default=None, description="隐患来源"),
    keyword: str | None = Query(default=None, description="按标题 / 编号 / 描述 / 责任人搜索"),
    open_only: bool = Query(default=False, description="只看未销号隐患"),
    overdue_only: bool = Query(default=False, description="只看逾期未整改隐患"),
) -> Page[HazardRead]:
    items, total = hazard_service.list_hazards(
        db,
        reservoir_id=reservoir_id,
        inspection_id=inspection_id,
        category=category.value if category else None,
        severity=severity.value if severity else None,
        status=hazard_status.value if hazard_status else None,
        source=source.value if source else None,
        keyword=keyword,
        open_only=open_only,
        overdue_only=overdue_only,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return Page.build(items=items, total=total, page=pagination.page, page_size=pagination.page_size)


@router.post(
    "",
    response_model=HazardDetail,
    status_code=status.HTTP_201_CREATED,
    summary="登记隐患",
)
def create_hazard(payload: HazardCreate, db: DbSession) -> HazardDetail:
    return hazard_service.create_hazard(db, payload)


@router.get(
    "/reopens",
    response_model=Page[HazardReopenRead],
    summary="分页查询重启申请",
)
def list_reopens(
    db: DbSession,
    pagination: PageParams,
    reopen_status: ReopenStatus | None = Query(default=None, alias="status", description="确认状态"),
    hazard_id: int | None = Query(default=None, description="按隐患过滤"),
) -> Page[HazardReopenRead]:
    items, total = hazard_service.list_reopen_requests(
        db,
        status=reopen_status.value if reopen_status else None,
        hazard_id=hazard_id,
        page=pagination.page,
        page_size=pagination.page_size,
    )
    return Page.build(items=items, total=total, page=pagination.page, page_size=pagination.page_size)


@router.get("/{hazard_id}", response_model=HazardDetail, summary="隐患详情（含整改流水）")
def get_hazard(hazard_id: int, db: DbSession) -> HazardDetail:
    return hazard_service.get_hazard(db, hazard_id)


@router.put("/{hazard_id}", response_model=HazardDetail, summary="更新隐患信息")
def update_hazard(hazard_id: int, payload: HazardUpdate, db: DbSession) -> HazardDetail:
    return hazard_service.update_hazard(db, hazard_id, payload)


@router.post(
    "/{hazard_id}/rectifications",
    response_model=HazardDetail,
    status_code=status.HTTP_201_CREATED,
    summary="追加整改跟踪记录",
)
def add_rectification(
    hazard_id: int, payload: HazardRectificationCreate, db: DbSession
) -> HazardDetail:
    return hazard_service.add_rectification(db, hazard_id, payload)


@router.post(
    "/{hazard_id}/transition",
    response_model=HazardDetail,
    summary="整改状态流转（开始整改 / 提交验收 / 销号 / 退回整改）",
    responses={409: {"description": "当前状态不允许该流转"}},
)
def transition_hazard(
    hazard_id: int, payload: HazardTransitionRequest, db: DbSession
) -> HazardDetail:
    return hazard_service.transition_hazard(db, hazard_id, payload)


@router.post(
    "/{hazard_id}/reopen",
    response_model=HazardReopenRead,
    status_code=status.HTTP_201_CREATED,
    summary="已销号隐患申请重启（登记重启原因，待确认）",
    responses={409: {"description": "隐患未销号或已有待确认的重启申请"}},
)
def apply_reopen(hazard_id: int, payload: HazardReopenCreate, db: DbSession) -> HazardReopenRead:
    return hazard_service.apply_reopen(db, hazard_id, payload)


@router.post(
    "/reopens/{reopen_id}/review",
    response_model=HazardDetail,
    summary="确认 / 驳回重启申请（确认需填写重启依据）",
    responses={
        409: {"description": "申请已处理或隐患状态不允许重启"},
        422: {"description": "确认重启但未填写依据"},
    },
)
def review_reopen(
    reopen_id: int, payload: HazardReopenReview, db: DbSession
) -> HazardDetail:
    _request, hazard = hazard_service.review_reopen(db, reopen_id, payload)
    if hazard is None:
        # 驳回：返回隐患当前详情，便于前端刷新
        hazard = hazard_service.get_hazard(db, _request.hazard_id)
    return hazard


@router.delete("/{hazard_id}", response_model=Message, summary="删除隐患及其整改流水")
def delete_hazard(hazard_id: int, db: DbSession) -> Message:
    hazard_service.delete_hazard(db, hazard_id)
    return Message(detail="隐患已删除", code="deleted")

