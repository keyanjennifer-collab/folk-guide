"""正式 AI 问答：赠送权益、安全拦截、历史和反馈测试。"""

import json
from datetime import timedelta

from fastapi.testclient import TestClient
import pytest

from app.config import get_settings
from app.database import SessionLocal
from app.ai_rate_limit import reset_ai_rate_limit_for_tests
from app.ai_service import question_requests_personal_context
from app.llm_provider import get_answer_provider, set_answer_provider
from app.main import app
from app.models import User
from app.time_service import utc_now_naive
from test_knowledge import ADMIN_HEADERS, cleanup_hash, upload
from app.web_search_service import get_web_search_provider, set_web_search_provider


class ReadyDirectProvider:
    """测试替身：验证关闭知识库时确实以空引用调用模型分支。"""

    model_name = "test-direct-model"
    ready = True

    def __init__(self, answer_text: str = "这是受约束的传统文化测试回答。") -> None:
        self.calls: list[dict] = []
        self.answer_text = answer_text

    def generate(
        self, question, contexts, *, use_knowledge_base=True, personal_context=None,
        web_results=None
    ):
        self.calls.append({
            "question": question,
            "contexts": contexts,
            "use_knowledge_base": use_knowledge_base,
            "personal_context": personal_context,
            "web_results": web_results,
        })
        return self.answer_text


class FakeWebSearchProvider:
    """验证开关关闭时不调用、打开后才把网页摘要传给模型。"""

    provider_name = "fake-search"
    ready = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    def search(self, query: str, *, max_results: int = 5) -> list[dict]:
        self.calls.append(query)
        return [{
            "title": "测试网页资料",
            "url": "https://example.com/test-source",
            "content": "这是未经审核的测试网页摘要。",
            "published_date": "2026-08-21",
        }]


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


def save_profile(
    client: TestClient,
    headers: dict[str, str],
    *,
    birth_date: str = "1995-06-18",
    time_known: bool = True,
) -> dict:
    """创建测试档案；不知道时辰时绝不附带birth_time。"""
    payload = {
        "calendar_type": "solar",
        "birth_date": birth_date,
        "time_known": time_known,
        "birth_city": "杭州",
    }
    if time_known:
        payload["birth_time"] = "14:30"
    response = client.put("/api/profiles/current", headers=headers, json=payload)
    assert response.status_code == 200
    return response.json()


@pytest.mark.parametrize("question", [
    "今天适合穿什么颜色？",
    "为什么我的个人排名和公共排名不同？",
    "我今天需要注意什么？",
    "根据我的生辰，今天适合用什么香？",
])
def test_personal_question_classifier_matches_product_questions(question: str):
    assert question_requests_personal_context(question) is True


@pytest.mark.parametrize("question", [
    "传统文化中五行怎样对应五色？",
    "今天是什么节气？",
    "《周易》主要讲什么？",
    "什么是八字？",
])
def test_general_culture_questions_do_not_read_personal_context(question: str):
    assert question_requests_personal_context(question) is False


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
        assert answered.json()["safety_status"] == "safe"
        assert answered.json()["citations"] == []
        assert answered.json()["remaining_today"] <= 19
        assert direct_provider.calls[-1]["contexts"] == []
        assert direct_provider.calls[-1]["use_knowledge_base"] is False
        assert direct_provider.calls[-1]["personal_context"] is None
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


def test_model_output_is_filtered_before_storage_and_response():
    """模型输出出现确定性收益承诺时，原文不能进入接口或历史。"""
    original = get_answer_provider()
    unsafe_provider = ReadyDirectProvider("根据你的生辰，今天一定会发财，投资稳赚不赔。")
    set_answer_provider(unsafe_provider)
    try:
        with TestClient(app) as client:
            headers = login(client, "unsafe-output-user")
            answered = client.post(
                "/api/ai/chat", headers=headers, json={"question": "五行文化是什么？"}
            )
            assert answered.status_code == 200
            result = answered.json()
            assert result["safety_status"] == "output_filtered"
            assert "一定会发财" not in result["answer"]
            history = client.get("/api/ai/history", headers=headers).json()
            assert "一定会发财" not in history[0]["answer"]
            client.delete("/api/account", headers=headers)
    finally:
        set_answer_provider(original)


def test_ai_short_window_rate_limit_returns_429_without_consuming_daily_quota(direct_provider):
    settings = get_settings()
    original_enabled = settings.ai_rate_limit_enabled
    original_max = settings.ai_rate_limit_max_requests
    original_window = settings.ai_rate_limit_window_seconds
    reset_ai_rate_limit_for_tests()
    settings.ai_rate_limit_enabled = True
    settings.ai_rate_limit_max_requests = 1
    settings.ai_rate_limit_window_seconds = 60
    try:
        with TestClient(app) as client:
            headers = login(client, "ai-rate-limit-user")
            before = client.get("/api/ai/quota", headers=headers).json()["normal_remaining"]
            first = client.post(
                "/api/ai/chat", headers=headers, json={"question": "五行文化是什么？"}
            )
            second = client.post(
                "/api/ai/chat", headers=headers, json={"question": "什么是二十四节气？"}
            )
            assert first.status_code == 200
            assert second.status_code == 429
            assert second.headers["retry-after"] == "60"
            after = client.get("/api/ai/quota", headers=headers).json()["normal_remaining"]
            assert after == before - 1
            client.delete("/api/account", headers=headers)
    finally:
        settings.ai_rate_limit_enabled = original_enabled
        settings.ai_rate_limit_max_requests = original_max
        settings.ai_rate_limit_window_seconds = original_window
        reset_ai_rate_limit_for_tests()


def test_web_search_is_strictly_optional_and_web_citation_is_separate(direct_provider):
    settings = get_settings()
    original_enabled = settings.ai_web_search_enabled
    original_always = settings.ai_web_search_always
    original_provider = get_web_search_provider()
    search = FakeWebSearchProvider()
    set_web_search_provider(search)
    try:
        with TestClient(app) as client:
            headers = login(client, "optional-web-search-user")
            settings.ai_web_search_enabled = False
            disabled = client.post(
                "/api/ai/chat", headers=headers, json={"question": "最新节气资料"}
            )
            assert disabled.status_code == 200
            assert search.calls == []
            assert direct_provider.calls[-1]["web_results"] == []
            assert disabled.json()["citations"] == []

            settings.ai_web_search_enabled = True
            settings.ai_web_search_always = True
            enabled = client.post(
                "/api/ai/chat", headers=headers, json={"question": "《周易》主要讲什么"}
            )
            assert enabled.status_code == 200
            assert search.calls == ["《周易》主要讲什么"]
            assert direct_provider.calls[-1]["web_results"][0]["url"] == "https://example.com/test-source"
            assert enabled.json()["citations"] == [{
                "kind": "web",
                "document_id": None,
                "chunk_id": None,
                "title": "测试网页资料",
                "heading": "2026-08-21",
                "source_name": "https://example.com/test-source",
                "page_start": None,
                "page_end": None,
            }]
            client.delete("/api/account", headers=headers)
    finally:
        settings.ai_web_search_enabled = original_enabled
        settings.ai_web_search_always = original_always
        set_web_search_provider(original_provider)


def test_personal_question_uses_same_daily_result_without_raw_profile(direct_provider):
    """个人问答必须复用页面同一份结果，且模型上下文不含账号或原始生辰。"""
    with TestClient(app) as client:
        headers = login(client, "personal-ai-context")
        save_profile(client, headers)
        expected = client.get("/api/daily", headers=headers)
        assert expected.status_code == 200

        answered = client.post(
            "/api/ai/chat", headers=headers, json={"question": "今天适合穿什么颜色？"}
        )
        assert answered.status_code == 200
        result = answered.json()
        assert result["category"] == "personal_daily"
        assert result["citations"] == [{
            "kind": "personal_daily",
            "document_id": None,
            "chunk_id": None,
            "title": "今日个人五色",
            "heading": expected.json()["date"],
            "source_name": (
                f"个人规则结果·完整四柱·{expected.json()['rule_version']}"
            ),
            "page_start": None,
            "page_end": None,
        }]

        personal_context = direct_provider.calls[-1]["personal_context"]
        assert personal_context["primary_color"] == expected.json()["primary_color"]
        assert personal_context["supporting_colors"] == expected.json()["supporting_colors"]
        assert personal_context["colors"] == [{
            key: item[key] for key in (
                "rank", "name", "element", "tendency", "suitable", "resistance",
                "advice", "incense", "scent", "reason",
            )
        } for item in expected.json()["colors"]]

        serialized = json.dumps(personal_context, ensure_ascii=False)
        for forbidden in (
            "birth_date", "birth_time", "birth_city", "openid", "phone_number",
            "user_id", "profile_version", "calendar_version", "config_fingerprint",
            "input_fingerprint", "entitlement_plan",
        ):
            assert forbidden not in serialized


def test_personal_question_without_profile_guides_user_and_does_not_consume(direct_provider):
    """缺档案时不调用模型，不生成臆测结果，也不扣赠送次数。"""
    with TestClient(app) as client:
        headers = login(client, "personal-ai-missing-profile")
        before = client.get("/api/ai/quota", headers=headers).json()["normal_remaining"]
        call_count = len(direct_provider.calls)

        answered = client.post(
            "/api/ai/chat", headers=headers, json={"question": "我今天适合用什么颜色？"}
        )
        assert answered.status_code == 200
        result = answered.json()
        assert result["category"] == "profile_required"
        assert result["remaining_today"] == before
        assert result["citations"] == []
        assert "本人档案" in result["answer"]
        assert len(direct_provider.calls) == call_count

        after = client.get("/api/ai/quota", headers=headers).json()["normal_remaining"]
        assert after == before


def test_unknown_birth_time_personal_context_stays_three_pillars(direct_provider):
    """不知道时辰时，问答上下文沿用三柱结果，不能在提示中补造时柱。"""
    with TestClient(app) as client:
        headers = login(client, "personal-ai-unknown-time")
        save_profile(client, headers, birth_date="1982-11-03", time_known=False)

        answered = client.post(
            "/api/ai/chat",
            headers=headers,
            json={"question": "根据我的生辰，今天适合用什么香？"},
        )
        assert answered.status_code == 200
        context = direct_provider.calls[-1]["personal_context"]
        assert context["precision_mode"] == "three_pillars"
        assert answered.json()["citations"][0]["source_name"].startswith("个人规则结果·三柱参考")


def test_personal_context_isolated_between_users(direct_provider):
    """两名用户连续提问时，各自上下文必须和各自 `/api/daily` 完全一致。"""
    with TestClient(app) as client:
        first = login(client, "personal-context-owner-one")
        second = login(client, "personal-context-owner-two")
        save_profile(client, first, birth_date="1995-06-18", time_known=True)
        save_profile(client, second, birth_date="1982-11-03", time_known=False)
        first_daily = client.get("/api/daily", headers=first).json()
        second_daily = client.get("/api/daily", headers=second).json()

        assert client.post(
            "/api/ai/chat", headers=first, json={"question": "我今天穿什么颜色？"}
        ).status_code == 200
        first_context = direct_provider.calls[-1]["personal_context"]
        assert client.post(
            "/api/ai/chat", headers=second, json={"question": "我今天穿什么颜色？"}
        ).status_code == 200
        second_context = direct_provider.calls[-1]["personal_context"]

        assert first_context["primary_color"] == first_daily["primary_color"]
        assert first_context["precision_mode"] == "four_pillars"
        assert second_context["primary_color"] == second_daily["primary_color"]
        assert second_context["precision_mode"] == "three_pillars"


def test_expired_user_cannot_load_personal_context(direct_provider):
    """权益校验先于档案和个人缓存读取，过期用户不能调用模型。"""
    with TestClient(app) as client:
        headers = login(client, "personal-ai-expired")
        save_profile(client, headers)
        user_id = client.get("/api/users/me", headers=headers).json()["id"]
        with SessionLocal() as db:
            user = db.get(User, user_id)
            assert user is not None
            user.created_at = utc_now_naive() - timedelta(days=10)
            db.commit()
        call_count = len(direct_provider.calls)

        denied = client.post(
            "/api/ai/chat", headers=headers, json={"question": "今天适合穿什么颜色？"}
        )
        assert denied.status_code == 403
        assert len(direct_provider.calls) == call_count


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
