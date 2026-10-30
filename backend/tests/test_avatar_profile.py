"""头像实际文件持久化、重新登录恢复、账号隔离与保存失败回滚。"""

import base64
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from app.avatar_service import avatar_directory, MAX_AVATAR_BYTES
from app.config import get_settings
from app.database import SessionLocal
from app.main import app, update_account_profile
from app.models import User
from app.schemas import UserProfileInput

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l1sAAAAASUVORK5CYII=")
ENCODED = base64.b64encode(PNG).decode()


def login(client, code):
    token = client.post("/api/auth/wechat", json={"code": code}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def avatar_client(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "knowledge_storage_root", str(tmp_path / "persistent-storage"))
    with TestClient(app) as client:
        code = "avatar-" + uuid4().hex
        headers = login(client, code)
        yield client, headers, code


def save(client, headers, nickname="我的头像"):
    response = client.put("/api/users/me/profile", headers=headers,
                          json={"nickname": nickname, "avatar_base64": ENCODED})
    assert response.status_code == 200, response.text
    return response.json()


def test_avatar_roundtrip_and_new_login_use_the_same_persistent_image(avatar_client):
    client, headers, code = avatar_client
    user = save(client, headers, "  自定义昵称  ")
    assert user["nickname"] == "自定义昵称"
    url = user["avatar_url"]
    assert url.startswith("/avatar-assets/") and "tmp" not in url
    path = avatar_directory() / url.rsplit("/", 1)[1]
    assert path.read_bytes() == PNG
    image = client.get(url)
    assert image.status_code == 200 and image.content == PNG
    assert image.headers["content-type"] == "image/png"
    assert image.headers["x-content-type-options"] == "nosniff"
    # 新客户端没有旧前端的缓存/临时文件，仍从账号和持久化目录恢复。
    with TestClient(app) as fresh_client:
        fresh_headers = login(fresh_client, code)
        current = fresh_client.get("/api/users/me", headers=fresh_headers).json()
        assert current["id"] == user["id"] and current["nickname"] == "自定义昵称"
        assert current["avatar_url"] == url
        assert fresh_client.get(url).content == PNG


def test_changing_avatar_removes_previous_file_and_nickname_only_keeps_current_file(avatar_client):
    client, headers, _ = avatar_client
    first = save(client, headers)
    second = save(client, headers, "新的昵称")
    assert first["avatar_url"] != second["avatar_url"]
    assert client.get(first["avatar_url"]).status_code == 404
    assert client.get(second["avatar_url"]).status_code == 200
    assert len(list(avatar_directory().iterdir())) == 1
    result = client.put("/api/users/me/profile", headers=headers,
                        json={"nickname": "只改昵称", "avatar_url": second["avatar_url"]})
    assert result.status_code == 200 and result.json()["avatar_url"] == second["avatar_url"]
    assert client.get(second["avatar_url"]).content == PNG


@pytest.mark.parametrize("temporary", ["wxfile://tmp/a.jpg", "http://tmp/a.jpg", "https://tmp/a.jpg",
                                      "file:///a.jpg", "../a.jpg", "data:image/png;base64,AAA"])
def test_backend_rejects_temporary_avatar_urls_without_losing_saved_profile(avatar_client, temporary):
    client, headers, _ = avatar_client
    user = save(client, headers)
    result = client.put("/api/users/me/profile", headers=headers,
                        json={"nickname": "不能误保存", "avatar_url": temporary})
    assert result.status_code == 400
    current = client.get("/api/users/me", headers=headers).json()
    assert current["nickname"] == user["nickname"] and current["avatar_url"] == user["avatar_url"]


def test_cannot_attach_another_accounts_avatar(avatar_client):
    client, owner, _ = avatar_client
    first = save(client, owner)
    other = login(client, "avatar-other-" + uuid4().hex)
    for url in [first["avatar_url"], "https://api.wusezhishi.com" + first["avatar_url"]]:
        result = client.put("/api/users/me/profile", headers=other,
                            json={"nickname": "另一个账号", "avatar_url": url})
        assert result.status_code == 400
    assert client.get("/api/users/me", headers=other).json()["avatar_url"] is None
    assert client.get(first["avatar_url"]).content == PNG


@pytest.mark.parametrize("encoded", ["invalid%base64", "", base64.b64encode(b"<svg>not an image</svg>").decode()])
def test_invalid_image_never_changes_saved_profile(avatar_client, encoded):
    client, headers, _ = avatar_client
    user = save(client, headers)
    result = client.put("/api/users/me/profile", headers=headers,
                        json={"nickname": "无效图片", "avatar_base64": encoded})
    assert result.status_code == 400
    assert client.get("/api/users/me", headers=headers).json()["avatar_url"] == user["avatar_url"]
    assert len(list(avatar_directory().iterdir())) == 1


def test_oversized_image_and_empty_nickname_are_rejected(avatar_client):
    client, headers, _ = avatar_client
    payload = base64.b64encode(b"x" * (MAX_AVATAR_BYTES + 1)).decode()
    result = client.put("/api/users/me/profile", headers=headers,
                        json={"nickname": "超大图片", "avatar_base64": payload})
    assert result.status_code == 413
    assert client.put("/api/users/me/profile", headers=headers,
                      json={"nickname": "   ", "avatar_base64": ENCODED}).status_code == 422
    assert not avatar_directory().exists()


def test_failed_database_commit_keeps_previous_avatar_and_cleans_new_file(avatar_client, monkeypatch):
    client, headers, _ = avatar_client
    first = save(client, headers)
    with SessionLocal() as db:
        user = db.get(User, first["id"])

        def fail_commit():
            raise RuntimeError("test database failure")

        monkeypatch.setattr(db, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="test database failure"):
            update_account_profile(UserProfileInput(nickname="失败的修改", avatar_base64=ENCODED), user, db)
    current = client.get("/api/users/me", headers=headers).json()
    assert current["nickname"] == first["nickname"] and current["avatar_url"] == first["avatar_url"]
    assert len(list(avatar_directory().iterdir())) == 1
    assert client.get(first["avatar_url"]).content == PNG


def test_account_deletion_cleans_avatar_file(avatar_client):
    client, headers, _ = avatar_client
    user = save(client, headers)
    assert client.delete("/api/account", headers=headers).status_code == 204
    assert client.get(user["avatar_url"]).status_code == 404


def test_avatar_requires_login_and_asset_path_cannot_traverse(avatar_client):
    client, _, _ = avatar_client
    assert client.put("/api/users/me/profile", json={"nickname": "未登录", "avatar_base64": ENCODED}).status_code in (401, 403)
    assert client.get("/avatar-assets/not-an-avatar.txt").status_code == 404
    assert client.get("/avatar-assets/%2e%2e%2fsecret.txt").status_code == 404
