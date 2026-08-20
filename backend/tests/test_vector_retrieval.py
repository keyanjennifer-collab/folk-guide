"""向量同步安全边界和混合检索的独立测试。"""

import hashlib

from fastapi.testclient import TestClient

from app.main import app
from test_knowledge import ADMIN_HEADERS, cleanup_hash, upload


def test_sync_and_hybrid_search_only_use_approved_chunks():
    content = ("立春是二十四节气之一。春季色彩建议需要结合可靠资料。" * 30).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    cleanup_hash(digest)
    with TestClient(app) as client:
        uploaded = upload(client, "vector-boundary.txt", content)
        document_id = uploaded.json()["id"]

        # 上传状态不能越过人工审核直接进入向量库。
        blocked = client.post(
            f"/api/admin/knowledge/documents/{document_id}/sync-vectors", headers=ADMIN_HEADERS
        )
        assert blocked.status_code == 409

        assert client.post(
            f"/api/admin/knowledge/documents/{document_id}/parse", headers=ADMIN_HEADERS
        ).status_code == 200
        approved = client.post(
            f"/api/admin/knowledge/documents/{document_id}/approve",
            headers=ADMIN_HEADERS,
            json={"approved_chunk_ids": None},
        )
        synced = client.post(
            f"/api/admin/knowledge/documents/{document_id}/sync-vectors", headers=ADMIN_HEADERS
        )
        assert synced.status_code == 200
        assert synced.json()["synced_chunk_count"] == approved.json()["approved_chunk_count"]
        assert synced.json()["embedding_model"] == "local-bigram-v1"

        results = client.get(
            "/api/admin/knowledge/hybrid-search",
            headers=ADMIN_HEADERS,
            params={"q": "立春节气色彩"},
        )
        assert results.status_code == 200
        assert results.json()[0]["document_id"] == document_id

        assert client.post(
            f"/api/admin/knowledge/documents/{document_id}/disable", headers=ADMIN_HEADERS
        ).status_code == 200
        assert client.get(
            "/api/admin/knowledge/hybrid-search", headers=ADMIN_HEADERS, params={"q": "立春节气"}
        ).json() == []
    cleanup_hash(digest)
