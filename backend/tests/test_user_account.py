"""当前账号状态和未配置微信手机号能力的测试。"""

from fastapi.testclient import TestClient

from app.main import app
from app.database import SessionLocal
from app.models import AIConversationMessage, AIServiceGrant, User
from sqlalchemy import select
from datetime import datetime, timedelta


def test_current_user_and_phone_configuration_boundary():
    with TestClient(app) as client:
        token = client.post("/api/auth/wechat", json={"code": "account-test-user"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        current = client.get("/api/users/me", headers=headers)
        assert current.status_code == 200
        assert current.json()["phone_bound"] is False
        assert "openid" not in current.json()

        # 测试环境未配置微信密钥，必须明确失败，不能相信前端伪造的号码。
        phone = client.post("/api/users/me/phone", headers=headers, json={"code": "fake-phone-code"})
        assert phone.status_code == 503


def test_delete_account_cleans_ai_personal_data():
    """注销必须清理正式AI历史和权益，不能只删除旧版聊天。"""
    with TestClient(app) as client:
        token = client.post("/api/auth/wechat", json={"code": "delete-ai-data-user"}).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        user_id = client.get("/api/users/me", headers=headers).json()["id"]
        with SessionLocal() as db:
            db.add(AIServiceGrant(
                user_id=user_id, grant_type="paid_30_days",
                start_at=datetime.utcnow(), end_at=datetime.utcnow() + timedelta(days=30),
            ))
            db.add(AIConversationMessage(
                user_id=user_id, question="测试", answer="测试", category="culture_knowledge",
                references_json="[]", model_name="test",
            ))
            db.commit()
        assert client.delete("/api/account", headers=headers).status_code == 204
        with SessionLocal() as db:
            assert db.get(User, user_id) is None
            assert db.scalar(select(AIServiceGrant).where(AIServiceGrant.user_id == user_id)) is None
            assert db.scalar(select(AIConversationMessage).where(AIConversationMessage.user_id == user_id)) is None
