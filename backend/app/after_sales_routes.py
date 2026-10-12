"""售后客服入口：只返回微信客服的公开接入参数。"""

import re
from urllib.parse import urlparse

from fastapi import APIRouter
from pydantic import BaseModel

from .config import get_settings


router = APIRouter(tags=["商城交易"])


class AfterSalesContact(BaseModel):
    available: bool
    corp_id: str
    url: str
    fallback_contact: str


@router.get("/api/after-sales/contact", response_model=AfterSalesContact, summary="获取售后微信客服入口")
def after_sales_contact():
    settings = get_settings()
    corp_id = settings.wecom_corp_id.strip()
    url = settings.wecom_customer_service_url.strip()
    try:
        parsed = urlparse(url)
    except ValueError:
        parsed = urlparse("")
    available = bool(
        re.fullmatch(r"[A-Za-z0-9_-]{3,128}", corp_id)
        and parsed.scheme == "https"
        and parsed.netloc == "work.weixin.qq.com"
        and re.fullmatch(r"/kfid/[A-Za-z0-9_-]+/?", parsed.path)
    )
    return AfterSalesContact(
        available=available, corp_id=corp_id if available else "", url=url if available else "",
        fallback_contact=settings.commerce_customer_service.strip(),
    )
