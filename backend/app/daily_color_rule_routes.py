"""今日五色可编辑规则模板下载与填写结果校验接口。"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from .admin_auth import require_admin
from .daily_color_rule_template import build_rule_template, parse_rule_template


router = APIRouter()
ADMIN_TAG = "今日五色·运营后台"


@router.get(
    "/api/admin/daily-color-rules/template.xlsx",
    tags=[ADMIN_TAG],
    summary="下载可编辑规则与测试案例模板",
)
def download_rule_template(_: str = Depends(require_admin)):
    """返回空白模板，供未来人工复核或自定义新规则版本。"""
    return Response(
        build_rule_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="daily-color-rule-template.xlsx"'},
    )


@router.post(
    "/api/admin/daily-color-rules/validate",
    tags=[ADMIN_TAG],
    summary="校验人工填写的规则表",
)
async def validate_rule_template(file: UploadFile = File(...), _: str = Depends(require_admin)):
    """只校验并返回摘要，本阶段不把规则写入数据库或设为正式启用。"""
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=422, detail="仅支持.xlsx规则文件")
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="规则文件不能超过5MB")
    try:
        config = parse_rule_template(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "valid": True,
        "version": config.version,
        "status": config.status,
        "approved_test_case_count": config.approved_test_case_count,
        "config_fingerprint": config.fingerprint(),
        "can_generate_formal_draft": config.status in {"expert_reviewed", "active"},
        "persisted": False,
    }
