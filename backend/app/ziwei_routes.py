"""登录用户专属的紫微起盘、合盘保存与读取接口。"""

import json

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from .auth import current_user
from .database import get_db
from .models import User, ZiweiChartRecord, ZiweiCompatibilityRecord
from .ziwei_schemas import ZiweiBirthInput, ZiweiChartOutput, ZiweiCompatibilityInput, ZiweiCompatibilityOutput
from .ziwei_service import build_compatibility, generate_chart


router = APIRouter(prefix="/api/ziwei", tags=["紫微起盘与合盘"])


def chart_output(record: ZiweiChartRecord) -> dict:
    chart = json.loads(record.chart_json)
    # 兼容首版已保存的记录：当时尚未记录用户选择的历法，仍可稳定展示实际公历。
    chart.setdefault("inputCalendar", {
        "calendarType": record.calendar_type, "sourceDate": record.birth_date.isoformat(),
        "isLeapMonth": record.is_leap_month,
        "solarDate": f"{chart['birthInfo']['year']:04d}-{chart['birthInfo']['month']:02d}-{chart['birthInfo']['day']:02d}",
    })
    return {"id": record.id, "label": record.label, "name": record.name, "birth_date": record.birth_date,
            "calendar_type": record.calendar_type, "is_leap_month": record.is_leap_month,
            "birth_time": record.birth_time, "gender": record.gender, "birth_location": record.birth_location,
            "chart": chart, "created_at": record.created_at, "updated_at": record.updated_at}


def person_snapshot(data: ZiweiBirthInput, chart: dict) -> dict:
    return {"label": data.label, "name": data.name, "birth_date": data.birth_date.isoformat(),
            "calendar_type": data.calendar_type, "is_leap_month": data.is_leap_month,
            "birth_time": data.birth_time, "gender": data.gender, "birth_location": data.birth_location, "chart": chart}


@router.post("/charts", response_model=ZiweiChartOutput, summary="起盘并保存我的紫微命盘")
def create_chart(data: ZiweiBirthInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        chart = generate_chart(data)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    record = ZiweiChartRecord(user_id=user.id, label=data.label, name=data.name, birth_date=data.birth_date,
                              calendar_type=data.calendar_type, is_leap_month=data.is_leap_month,
                              birth_time=data.birth_time, gender=data.gender, birth_location=data.birth_location,
                              chart_json=json.dumps(chart, ensure_ascii=False, separators=(",", ":")))
    db.add(record)
    db.commit()
    db.refresh(record)
    return chart_output(record)


@router.get("/charts", response_model=list[ZiweiChartOutput], summary="读取我保存的紫微命盘")
def list_charts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    records = db.scalars(select(ZiweiChartRecord).where(ZiweiChartRecord.user_id == user.id)
                         .order_by(desc(ZiweiChartRecord.updated_at))).all()
    return [chart_output(record) for record in records]


@router.delete("/charts/{chart_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除我的紫微命盘")
def delete_chart(chart_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    record = db.scalar(select(ZiweiChartRecord).where(ZiweiChartRecord.id == chart_id, ZiweiChartRecord.user_id == user.id))
    if record is None:
        raise HTTPException(404, "命盘不存在")
    db.delete(record)
    db.commit()
    return Response(status_code=204)


@router.post("/compatibilities", response_model=ZiweiCompatibilityOutput, summary="双人合盘并保存结果")
def create_compatibility(data: ZiweiCompatibilityInput, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        chart_a, chart_b = generate_chart(data.person_a), generate_chart(data.person_b)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    result = build_compatibility(chart_a, chart_b, data.relation_type)
    record = ZiweiCompatibilityRecord(
        user_id=user.id, relation_type=data.relation_type,
        person_a_json=json.dumps(person_snapshot(data.person_a, chart_a), ensure_ascii=False, separators=(",", ":")),
        person_b_json=json.dumps(person_snapshot(data.person_b, chart_b), ensure_ascii=False, separators=(",", ":")),
        result_json=json.dumps(result, ensure_ascii=False, separators=(",", ":")),
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return {"id": record.id, "relation_type": record.relation_type, "person_a": json.loads(record.person_a_json),
            "person_b": json.loads(record.person_b_json), "result": json.loads(record.result_json), "created_at": record.created_at}


@router.get("/compatibilities", response_model=list[ZiweiCompatibilityOutput], summary="读取我保存的合盘记录")
def list_compatibilities(user: User = Depends(current_user), db: Session = Depends(get_db)):
    records = db.scalars(select(ZiweiCompatibilityRecord).where(ZiweiCompatibilityRecord.user_id == user.id)
                         .order_by(desc(ZiweiCompatibilityRecord.created_at))).all()
    return [{"id": item.id, "relation_type": item.relation_type, "person_a": json.loads(item.person_a_json),
             "person_b": json.loads(item.person_b_json), "result": json.loads(item.result_json), "created_at": item.created_at} for item in records]
