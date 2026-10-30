"""把用户选择的临时头像保存到已有持久化存储，数据库只保存稳定访问路径。"""

import base64
import binascii
from contextlib import suppress
import logging
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException
from fastapi.responses import FileResponse

from .config import get_settings

MAX_AVATAR_BYTES = 2 * 1024 * 1024
MAX_AVATAR_BASE64_LENGTH = ((MAX_AVATAR_BYTES + 2) // 3) * 4
AVATAR_FILENAME = re.compile(r"[1-9][0-9]*-[0-9a-f]{32}\.(?:jpg|png|webp)")
logger = logging.getLogger(__name__)


def avatar_directory() -> Path:
    configured = get_settings().knowledge_storage_root.strip()
    root = Path(configured) if configured else Path(__file__).resolve().parents[1] / "storage" / "knowledge"
    # 生产环境复用 knowledge_data 挂载，不需要新增环境变量或数据卷。
    return root / "user-avatars"


def _owned_avatar_path(url: str | None, user_id: int) -> Path | None:
    prefix = f"/avatar-assets/{user_id}-"
    if not url or not url.startswith(prefix):
        return None
    filename = url.removeprefix("/avatar-assets/")
    return avatar_directory() / filename if AVATAR_FILENAME.fullmatch(filename) else None


def validate_avatar_url(url: str | None, user_id: int) -> str | None:
    if not url or url == "/assets/brand/logo-ai.png":
        return None
    if url.startswith("/avatar-assets/"):
        path = _owned_avatar_path(url, user_id)
        if path is None or not path.is_file():
            raise HTTPException(400, "头像文件无效，请重新选择头像后保存")
        return url
    try:
        parsed = urlsplit(url)
        if (parsed.scheme == "https" and parsed.hostname
                and parsed.hostname.lower() not in {"tmp", "usr", "localhost"}
                and not parsed.username and not parsed.password):
            if parsed.path.startswith("/avatar-assets/"):
                return validate_avatar_url(parsed.path, user_id)
            return url
    except ValueError:
        pass
    raise HTTPException(400, "不能保存临时头像地址，请重新选择头像后保存")


def save_avatar(encoded: str, user_id: int) -> str:
    if len(encoded) > MAX_AVATAR_BASE64_LENGTH:
        raise HTTPException(413, "头像不能超过2MB")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(400, "头像文件编码无效，请重新选择") from exc
    if len(content) > MAX_AVATAR_BYTES:
        raise HTTPException(413, "头像不能超过2MB")
    if len(content) >= 24 and content.startswith(b"\x89PNG\r\n\x1a\n"):
        suffix = "png"
    elif len(content) >= 4 and content.startswith(b"\xff\xd8\xff") and content.endswith(b"\xff\xd9"):
        suffix = "jpg"
    elif len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        suffix = "webp"
    else:
        raise HTTPException(400, "头像仅支持PNG、JPG、WebP图片")
    filename = f"{user_id}-{secrets.token_hex(16)}.{suffix}"
    path = avatar_directory() / filename
    created = False
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as target:
            created = True
            target.write(content)
    except OSError as exc:
        if created:
            with suppress(OSError):
                path.unlink(missing_ok=True)
        raise HTTPException(503, "头像保存失败，请稍后重试") from exc
    return f"/avatar-assets/{filename}"


def remove_avatar(url: str | None, user_id: int) -> None:
    path = _owned_avatar_path(url, user_id)
    if path is not None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("Unable to remove previous avatar for user %s", user_id)


def avatar_file_response(filename: str) -> FileResponse:
    if not AVATAR_FILENAME.fullmatch(filename):
        raise HTTPException(404, "头像不存在")
    path = avatar_directory() / filename
    if not path.is_file():
        raise HTTPException(404, "头像不存在")
    mime = {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[path.suffix]
    return FileResponse(path, media_type=mime,
                        headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=86400"})
