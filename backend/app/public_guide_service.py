"""今日五色状态机、审计、Excel 模板和批量解析。"""

import io
import json
import re
from datetime import date, datetime

from openpyxl import Workbook, load_workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import PublicGuide, PublicGuideAudit
from .public_guide_schemas import PublicGuideInput
from .time_service import beijing_today


EXCEL_HEADERS = [
    "日期", "星期", "农历", "节气", "当日干支", "排名", "颜色", "五行", "顺畅度",
    "适合事项", "可能阻力", "行动建议", "商品编码", "香品名称", "香气描述", "分享标题",
    "分享摘要", "推送摘要", "规则版本",
]


def payload_dict(guide: PublicGuide) -> dict:
    """读取数据库中的每日内容 JSON。"""
    return json.loads(guide.payload_json)


def guide_output(guide: PublicGuide) -> dict:
    """合并内容 JSON 和状态、版本、发布时间等数据库字段。"""
    return {
        **payload_dict(guide),
        "id": guide.id,
        "status": guide.status,
        "version": guide.version,
        "scheduled_at": guide.scheduled_at,
        "published_at": guide.published_at,
        "created_at": guide.created_at,
        "updated_at": guide.updated_at,
    }


def audit(db: Session, guide: PublicGuide, action: str, operator: str, before: str | None, detail: dict | None = None):
    """写入状态变化审计；与业务修改放在同一个数据库事务中提交。"""
    db.add(PublicGuideAudit(
        guide_id=guide.id,
        action=action,
        operator=operator,
        before_status=before,
        after_status=guide.status,
        detail_json=json.dumps(detail, ensure_ascii=False) if detail else None,
    ))


def save_draft(db: Session, data: PublicGuideInput, operator: str) -> tuple[PublicGuide, bool]:
    """新建草稿；若当天已存在则由调用者决定是否走更新逻辑。"""
    guide = db.scalar(select(PublicGuide).where(PublicGuide.guide_date == data.guide_date))
    created = guide is None
    if guide is None:
        guide = PublicGuide(guide_date=data.guide_date, payload_json="{}")
        db.add(guide)
        db.flush()
    elif guide.status == "published":
        raise ValueError("已发布内容请先撤回后再修改")
    before = guide.status
    guide.payload_json = json.dumps(data.model_dump(mode="json"), ensure_ascii=False)
    guide.status = "draft"
    guide.scheduled_at = None
    guide.version = 1 if created else guide.version + 1
    audit(db, guide, "create" if created else "update", operator, before)
    db.commit()
    db.refresh(guide)
    return guide, created


def set_status(db: Session, guide: PublicGuide, target: str, operator: str, action: str, scheduled_at: datetime | None = None):
    """校验状态流转并记录操作，防止跳过审核直接发布。"""
    before = guide.status
    guide.status = target
    guide.scheduled_at = scheduled_at
    if target == "published":
        guide.published_at = datetime.utcnow()
    audit(db, guide, action, operator, before)
    db.commit()
    db.refresh(guide)
    return guide


def publish_due_guides(db: Session) -> None:
    """把到期的 scheduled 内容发布；当前由读取接口触发，生产可改定时任务。"""
    # TODO（上线前）：改为独立定时任务并使用数据库锁，避免多实例同时发布同一条内容。
    now = datetime.utcnow()
    due = db.scalars(select(PublicGuide).where(
        PublicGuide.status == "scheduled",
        PublicGuide.scheduled_at.is_not(None),
        PublicGuide.scheduled_at <= now,
    )).all()
    for guide in due:
        before = guide.status
        guide.status = "published"
        guide.published_at = now
        audit(db, guide, "auto_publish", "system", before)
    if due:
        db.commit()


def build_excel_template() -> bytes:
    """在内存中生成 Excel 模板，不在服务器留下临时文件。"""
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "每日五色导入"
    sheet.append(EXCEL_HEADERS)
    colors = [
        (1, "绿色系", "木", "GREEN", "青木"),
        (2, "黑色系", "水", "BLACK", "墨沉"),
        (3, "黄色系", "土", "GOLD", "黄檀"),
        (4, "白色系", "金", "WHITE", "白桂"),
        (5, "红色系", "火", "RED", "朱蜜"),
    ]
    smoothness = ["今天很顺", "比较合适", "平稳一般", "会比较累", "成效偏弱"]
    for index, (rank, color, element, product, incense_name) in enumerate(colors):
        sheet.append([
            beijing_today().isoformat(), "星期一", "农历示例", "节气示例", "甲子", rank, color, element,
            smoothness[index], "合作、沟通", "可能需要更多耐心", "先确认重点再行动", product,
            incense_name, "香气描述示例", "今日五色排名", "完整五色建议已更新",
            "今日五色已更新", "manual-v1",
        ])
    for column in sheet.columns:
        sheet.column_dimensions[column[0].column_letter].width = 18
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _split_items(value) -> list[str]:
    """把 Excel 单元格中的换行或分隔文本转换为列表。"""
    return [item.strip() for item in re.split(r"[、,，;；]", str(value or "")) if item.strip()]


def parse_excel(content: bytes) -> list[PublicGuideInput]:
    """解析整张表并通过 Pydantic 逐行校验，错误会指出具体行。"""
    workbook = load_workbook(io.BytesIO(content), data_only=True)
    sheet = workbook.active
    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Excel为空")
    headers = [str(value or "").strip() for value in rows[0]]
    missing = [header for header in EXCEL_HEADERS if header not in headers]
    if missing:
        raise ValueError(f"缺少Excel列：{', '.join(missing)}")
    indexes = {header: headers.index(header) for header in EXCEL_HEADERS}
    grouped: dict[date, list[dict]] = {}
    common: dict[date, dict] = {}
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(value is not None for value in row):
            continue
        raw_date = row[indexes["日期"]]
        try:
            guide_date = raw_date.date() if isinstance(raw_date, datetime) else date.fromisoformat(str(raw_date).strip())
        except Exception as exc:
            raise ValueError(f"第{row_number}行日期格式错误") from exc
        item = {
            "rank": row[indexes["排名"]], "color": row[indexes["颜色"]], "element": row[indexes["五行"]],
            "smoothness": row[indexes["顺畅度"]], "suitable": _split_items(row[indexes["适合事项"]]),
            "resistance": row[indexes["可能阻力"]], "advice": row[indexes["行动建议"]],
            "product_code": row[indexes["商品编码"]], "incense_name": row[indexes["香品名称"]],
            "scent": row[indexes["香气描述"]],
        }
        grouped.setdefault(guide_date, []).append(item)
        common.setdefault(guide_date, {
            "guide_date": guide_date, "weekday": row[indexes["星期"]], "lunar_date": row[indexes["农历"]],
            "solar_term": row[indexes["节气"]], "day_ganzhi": row[indexes["当日干支"]],
            "share_title": row[indexes["分享标题"]], "share_summary": row[indexes["分享摘要"]],
            "push_summary": row[indexes["推送摘要"]], "rule_version": row[indexes["规则版本"]] or "manual-v1",
        })
    if not grouped:
        raise ValueError("Excel没有可导入数据")
    return [PublicGuideInput(**common[day], items=items) for day, items in sorted(grouped.items())]
"""今日五色的状态机、审计记录、Excel 模板和批量解析。"""
