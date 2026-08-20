"""正式 AI 问答：赠送权益、安全拦截、历史和反馈测试。"""

from fastapi.testclient import TestClient
import pytest

from app.config import get_settings
from app.llm_provider import get_answer_provider, set_answer_provider
from app.main import app
from test_knowledge import ADMIN_HEADERS, cleanup_hash, upload


class ReadyDirectProvider:
    """测试替身：验证关闭知识库时确实以空引用调用模型分支。"""

    model_name = "test-direct-model"
    ready = True

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def generate(self, question, contexts, *, use_knowledge_base=True):
        self.calls.append({
            "question": question,
            "contexts": contexts,
            "use_knowledge_base": use_knowledge_base,
        })
        return "这是受约束的传统文化测试回答。"


@pytest.fixture(autouse=True)
def direct_provider():
    original = get_answer_provider()
    provider = ReadyDirectProvider()
    set_answer_provider(provider)
    yield provider
    set_answer_provider(original)


def login(client: TestClient, code: str) -> dict[str, str]:
    """创建独立测试用户并返回登录请求头。"""
    token = client.post("/api/auth/wechat", json={"code": code}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_new_user_quota_chat_history_feedback_and_safety(direct_provider):
    with TestClient(app) as client:
        headers = login(client, "formal-ai-user")
        quota = client.get("/api/ai/quota", headers=headers)
        assert quota.status_code == 200
        assert quota.json()["plan"] == "new_user_3_days"
        assert quota.json()["normal_limit"] == 20
        assert quota.json()["comparison_limit"] == 2
        assert quota.json()["answer_ready"] is True
        assert "knowledge_ready" not in quota.json()

        answered = client.post(
            "/api/ai/chat", headers=headers, json={"question": "什么是二十四节气？"}
        )
        assert answered.status_code == 200
        assert answered.json()["category"] == "culture_knowledge"
        assert answered.json()["blocked"] is False
        assert answered.json()["citations"] == []
        assert answered.json()["remaining_today"] <= 19
        assert direct_provider.calls[-1]["contexts"] == []
        assert direct_provider.calls[-1]["use_knowledge_base"] is False
        message_id = answered.json()["message_id"]

        blocked = client.post(
            "/api/ai/chat", headers=headers, json={"question": "请预测我什么时候死亡"}
        )
        assert blocked.status_code == 200
        assert blocked.json()["blocked"] is True
        assert blocked.json()["model_name"] == "safety-rule-v1"

        history = client.get("/api/ai/history", headers=headers)
        assert history.status_code == 200
        assert len(history.json()) >= 2

        feedback = client.put(
            f"/api/ai/messages/{message_id}/feedback",
            headers=headers,
            json={"rating": "helpful", "note": "引用形式清楚"},
        )
        assert feedback.status_code == 200
        assert feedback.json()["feedback"] == "helpful"


def test_history_and_feedback_are_isolated_by_user():
    with TestClient(app) as client:
        first = login(client, "formal-ai-owner")
        second = login(client, "formal-ai-other")
        message = client.post("/api/ai/chat", headers=first, json={"question": "解释五行文化"}).json()
        denied = client.put(
            f"/api/ai/messages/{message['message_id']}/feedback",
            headers=second,
            json={"rating": "unhelpful"},
        )
        assert denied.status_code == 404


def test_future_knowledge_base_switch_restores_retrieval_and_citations(direct_provider):
    """防止当前关闭知识库时误删未来true分支。"""
    import hashlib

    content = ("五行相生包含木火土金水之间的传统关系。" * 30).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    cleanup_hash(digest)
    settings = get_settings()
    original_switch = settings.ai_use_knowledge_base
    try:
        settings.ai_use_knowledge_base = True
        with TestClient(app) as client:
            uploaded = upload(client, "future-rag.txt", content)
            document_id = uploaded.json()["id"]
            assert client.post(
                f"/api/admin/knowledge/documents/{document_id}/parse", headers=ADMIN_HEADERS
            ).status_code == 200
            assert client.post(
                f"/api/admin/knowledge/documents/{document_id}/approve",
                headers=ADMIN_HEADERS,
                json={"approved_chunk_ids": None},
            ).status_code == 200

            headers = login(client, "future-rag-user")
            quota = client.get("/api/ai/quota", headers=headers).json()
            assert quota["answer_ready"] is True
            answered = client.post(
                "/api/ai/chat", headers=headers, json={"question": "五行相生"}
            )
            assert answered.status_code == 200
            assert answered.json()["citations"]
            assert direct_provider.calls[-1]["contexts"]
            assert direct_provider.calls[-1]["use_knowledge_base"] is True
    finally:
        settings.ai_use_knowledge_base = original_switch
        cleanup_hash(digest)
