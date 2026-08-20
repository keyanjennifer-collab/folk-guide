"""今日五色公开读取和运营后台接口。"""

from datetime import date, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pathlib import Path
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .admin_auth import require_admin
from .database import get_db
from .daily_color_cache_service import ensure_public_color_cache, warm_public_color_cache
from .models import PublicGuide, PublicGuideAudit
from .public_guide_schemas import AuditOutput, ImportResult, PublicGuideInput, PublicGuideOutput, ScheduleGuideInput
from .public_guide_service import (
    build_excel_template,
    guide_output,
    parse_excel,
    payload_dict,
    publish_due_guides,
    save_draft,
    set_status,
)
from .time_service import beijing_today


router = APIRouter()
PUBLIC_TAG = "今日五色·用户端"
ADMIN_TAG = "今日五色·运营后台"
ADMIN_PAGE = Path(__file__).with_name("static") / "admin_public_guides.html"


@router.get("/admin/public-guides", include_in_schema=False)
def admin_page():
    """返回今日五色本地运营页面。"""
    return FileResponse(ADMIN_PAGE)


def get_guide_or_404(db: Session, guide_date: date) -> PublicGuide:
    """按日期取运营内容，不存在时统一返回 404。"""
    guide = db.scalar(select(PublicGuide).where(PublicGuide.guide_date == guide_date))
    if guide is None:
        raise HTTPException(status_code=404, detail="该日期内容不存在")
    return guide


@router.get(
    "/api/public-guides/today",
    response_model=PublicGuideInput,
    tags=[PUBLIC_TAG],
    summary="读取今日已发布的五色内容",
)
def public_today(db: Session = Depends(get_db)):
    """人工发布内容优先；没有人工内容时返回规则缓存并预热未来7天。"""
    publish_due_guides(db)
    # “今天”必须按北京时间自然日计算，不能依赖服务器安装在哪个时区。
    today = beijing_today()
    # 无论今天是否有人工发布内容，都维护未来7天自动规则缓存；两者分表保存，不覆盖。
    automatic_payloads = warm_public_color_cache(db, today)
    guide = db.scalar(select(PublicGuide).where(PublicGuide.guide_date == today, PublicGuide.status == "published"))
    if guide is not None:
        return payload_dict(guide)
    return automatic_payloads[today]


@router.get(
    "/api/public-guides/{guide_date}",
    response_model=PublicGuideInput,
    tags=[PUBLIC_TAG],
    summary="按日期读取已发布的五色内容",
)
def public_by_date(guide_date: date, db: Session = Depends(get_db)):
    """人工发布内容优先；未来7天范围内允许读取自动规则缓存。"""
    publish_due_guides(db)
    guide = db.scalar(select(PublicGuide).where(PublicGuide.guide_date == guide_date, PublicGuide.status == "published"))
    if guide is not None:
        return payload_dict(guide)
    today = beijing_today()
    if today <= guide_date < today + timedelta(days=7):
        payload = ensure_public_color_cache(db, guide_date)
        db.commit()
        return payload
    raise HTTPException(status_code=404, detail="该日期没有已发布内容")


@router.get(
    "/api/admin/public-guides",
    response_model=list[PublicGuideOutput],
    tags=[ADMIN_TAG],
    summary="查询每日五色后台内容列表",
)
def admin_list(
    status: str | None = Query(default=None, description="可选状态：draft、reviewing、scheduled、published、withdrawn"),
    _: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """运营列表支持状态和日期范围筛选。"""
    publish_due_guides(db)
    query = select(PublicGuide).order_by(desc(PublicGuide.guide_date))
    if status:
        query = query.where(PublicGuide.status == status)
    return [guide_output(guide) for guide in db.scalars(query).all()]


@router.get(
    "/api/admin/public-guides/template.xlsx",
    tags=[ADMIN_TAG],
    summary="下载每日五色Excel导入模板",
)
def admin_template(_: str = Depends(require_admin)):
    """下载字段固定的 Excel 模板，减少批量导入格式错误。"""
    return Response(
        build_excel_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="public-guide-template.xlsx"'},
    )


@router.post(
    "/api/admin/public-guides",
    response_model=PublicGuideOutput,
    tags=[ADMIN_TAG],
    summary="创建指定日期的每日五色草稿",
)
def admin_create(data: PublicGuideInput, operator: str = Depends(require_admin), db: Session = Depends(get_db)):
    """创建指定日期草稿；日期重复时由服务层拒绝。"""
    try:
        guide, _ = save_draft(db, data, operator)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return guide_output(guide)


@router.get(
    "/api/admin/public-guides/{guide_date}",
    response_model=PublicGuideOutput,
    tags=[ADMIN_TAG],
    summary="读取指定日期的后台内容",
)
def admin_get(guide_date: date, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    """后台读取某天内容，包括尚未公开的状态。"""
    return guide_output(get_guide_or_404(db, guide_date))


@router.put(
    "/api/admin/public-guides/{guide_date}",
    response_model=PublicGuideOutput,
    tags=[ADMIN_TAG],
    summary="修改指定日期的每日五色草稿",
)
def admin_update(guide_date: date, data: PublicGuideInput, operator: str = Depends(require_admin), db: Session = Depends(get_db)):
    """修改草稿内容并增加版本号，已发布内容不能直接覆盖。"""
    if data.guide_date != guide_date:
        raise HTTPException(status_code=422, detail="路径日期与内容日期不一致")
    try:
        guide, _ = save_draft(db, data, operator)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return guide_output(guide)


@router.post(
    "/api/admin/public-guides/{guide_date}/review",
    response_model=PublicGuideOutput,
    tags=[ADMIN_TAG],
    summary="将草稿提交审核",
)
def admin_review(guide_date: date, operator: str = Depends(require_admin), db: Session = Depends(get_db)):
    """把草稿提交为待审核状态。"""
    guide = get_guide_or_404(db, guide_date)
    if guide.status != "draft":
        raise HTTPException(status_code=409, detail="只有草稿可以提交审核")
    return guide_output(set_status(db, guide, "reviewing", operator, "submit_review"))


@router.post(
    "/api/admin/public-guides/{guide_date}/schedule",
    response_model=PublicGuideOutput,
    tags=[ADMIN_TAG],
    summary="设置审核内容的定时发布时间",
)
def admin_schedule(guide_date: date, data: ScheduleGuideInput, operator: str = Depends(require_admin), db: Session = Depends(get_db)):
    """审核后设置定时发布时间。"""
    guide = get_guide_or_404(db, guide_date)
    if guide.status != "reviewing":
        raise HTTPException(status_code=409, detail="只有待审核内容可以排期")
    scheduled = data.scheduled_at
    if scheduled.tzinfo is not None:
        scheduled = scheduled.astimezone(timezone.utc).replace(tzinfo=None)
    return guide_output(set_status(db, guide, "scheduled", operator, "schedule", scheduled))


@router.post(
    "/api/admin/public-guides/{guide_date}/publish",
    response_model=PublicGuideOutput,
    tags=[ADMIN_TAG],
    summary="立即发布审核内容",
)
def admin_publish(guide_date: date, operator: str = Depends(require_admin), db: Session = Depends(get_db)):
    """立即发布审核通过的内容。"""
    guide = get_guide_or_404(db, guide_date)
    if guide.status not in {"reviewing", "scheduled"}:
        raise HTTPException(status_code=409, detail="只有待审核或待发布内容可以发布")
    return guide_output(set_status(db, guide, "published", operator, "publish"))


@router.post(
    "/api/admin/public-guides/{guide_date}/withdraw",
    response_model=PublicGuideOutput,
    tags=[ADMIN_TAG],
    summary="撤回已经发布的每日五色",
)
def admin_withdraw(guide_date: date, operator: str = Depends(require_admin), db: Session = Depends(get_db)):
    """撤回已发布内容，公开接口会立刻不可见。"""
    guide = get_guide_or_404(db, guide_date)
    if guide.status != "published":
        raise HTTPException(status_code=409, detail="只有已发布内容可以撤回")
    return guide_output(set_status(db, guide, "withdrawn", operator, "withdraw"))


@router.post(
    "/api/admin/public-guides/import",
    response_model=ImportResult,
    tags=[ADMIN_TAG],
    summary="批量导入每日五色Excel文件",
)
async def admin_import(
    file: UploadFile = File(...),
    operator: str = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """解析并完整校验 Excel，按 overwrite 参数决定是否覆盖现有草稿。"""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=422, detail="仅支持.xlsx文件")
    # 当前模板文件体积很小，可一次读入内存；若将来放宽大小应改成受限流式处理。
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Excel不能超过5MB")
    try:
        guides = parse_excel(content)
        for data in guides:
            existing = db.scalar(select(PublicGuide).where(PublicGuide.guide_date == data.guide_date))
            if existing and existing.status == "published":
                raise ValueError(f"{data.guide_date}已发布，请先撤回后再导入")
        created = updated = 0
        for data in guides:
            _, is_created = save_draft(db, data, operator)
            created += int(is_created)
            updated += int(not is_created)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ImportResult(created=created, updated=updated, dates=[guide.guide_date for guide in guides])


@router.get(
    "/api/admin/public-guides/{guide_date}/audits",
    response_model=list[AuditOutput],
    tags=[ADMIN_TAG],
    summary="查看指定日期内容的操作审计",
)
def admin_audits(guide_date: date, _: str = Depends(require_admin), db: Session = Depends(get_db)):
    """查看指定日期内容的完整操作记录。"""
    guide = get_guide_or_404(db, guide_date)
    audits = db.scalars(select(PublicGuideAudit).where(PublicGuideAudit.guide_id == guide.id).order_by(PublicGuideAudit.id)).all()
    return audits
"""今日五色的公开读取和运营后台接口，写操作全部要求管理员身份。"""
