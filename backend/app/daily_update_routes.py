"""每日缓存任务的管理员状态与手动补跑接口。"""

from fastapi import APIRouter, Depends, Query

from .admin_auth import require_admin
from .daily_update_schemas import DailyUpdateInput, DailyUpdateOutput
from .daily_update_service import list_daily_update_results, run_daily_cache_update_with_retry


router = APIRouter(prefix="/api/admin/daily-cache", tags=["每日缓存·运维"])


@router.get(
    "/runs",
    response_model=list[DailyUpdateOutput],
    summary="查看最近每日缓存运行结果",
)
def list_runs(
    limit: int = Query(default=30, ge=1, le=100),
    _: str = Depends(require_admin),
):
    """按日期倒序读取任务状态，只返回汇总数量，不暴露任何用户资料。"""
    return [result.to_dict() for result in list_daily_update_results(limit)]


@router.post(
    "/run",
    response_model=DailyUpdateOutput,
    summary="手动补跑或重跑每日缓存",
)
def run_now(data: DailyUpdateInput, _: str = Depends(require_admin)):
    """执行与零点调度完全相同的任务。

    默认已成功的同日任务会幂等跳过。只有运营人员明确提交 ``force=true`` 时才重算；
    即使强制重算，也不会抢占另一个仍持有有效租约的worker。
    """
    result = run_daily_cache_update_with_retry(
        data.target_date,
        trigger="manual",
        force=data.force,
    )
    return result.to_dict()
