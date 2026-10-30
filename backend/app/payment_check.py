"""单笔支付核查：默认只读，--sync 仅补记经微信核实的待付款订单。"""

import argparse
import json
from urllib.parse import urlsplit

from sqlalchemy import select

from .commerce_models import Order
from .config import get_settings
from .database import SessionLocal
from .entitlements import feature_access_for_user
from .models import User
from .order_routes import reconcile_payment
from .wechat_pay import WechatPayError, query_payment


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("order_number")
    parser.add_argument("--sync", action="store_true", help="核实成功后补记仍为 pending 的订单；不扣款、不退款")
    args = parser.parse_args()
    settings = get_settings()
    with SessionLocal() as db:
        order = db.scalar(select(Order).where(Order.number == args.order_number))
        if order is None:
            print(json.dumps({"error": "本地订单不存在"}, ensure_ascii=False))
            return 1
        result = {
            "order_number": order.number, "local_status_before": order.status,
            "local_total_fen": order.total_fen,
            "has_prepay_id": bool(order.payment_prepay_id),
            "api_v3_key_is_32_bytes": len(settings.wechat_pay_api_v3_key.encode()) == 32,
            "payment_notify_path_matches": urlsplit(settings.wechat_pay_notify_url).path == "/api/payments/wechat/notify",
        }
        try:
            if args.sync and order.status == "pending" and order.payment_prepay_id:
                state = reconcile_payment(db, order)
                result["wechat_trade_state"] = state
            else:
                resource = query_payment(order.number)
                owner = db.get(User, order.user_id)
                result.update({
                    "wechat_trade_state": resource.get("trade_state"),
                    "merchant_matches": resource.get("mchid") == settings.wechat_pay_mch_id,
                    "app_matches": resource.get("appid") == settings.wechat_app_id,
                    "order_number_matches": resource.get("out_trade_no") == order.number,
                    "amount_matches": (resource.get("amount") or {}).get("total") == order.total_fen,
                    "payer_matches": bool(owner and (resource.get("payer") or {}).get("openid") == owner.openid),
                })
                if args.sync and order.status == "cancelled":
                    result["needs_review"] = "本地订单已取消，保留现状；需核对库存及是否已退款后处理"
            db.refresh(order)
            owner = db.get(User, order.user_id)
            access = feature_access_for_user(db, owner) if owner else None
            result.update({"local_status_after": order.status,
                           "has_paid_at": order.paid_at is not None,
                           "entitlement_plan": access.plan if access else None})
        except WechatPayError as exc:
            db.rollback()
            result["error"] = str(exc)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
