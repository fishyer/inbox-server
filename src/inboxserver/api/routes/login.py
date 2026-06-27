"""代登录端点：POST /login/{platform}/cookie（写凭据）/ GET /login/{platform}/status（查登录态）。

POST：cookie 凭据加密落库到 credentials 表，name 约定 {platform}_creds（与
channels.yaml 的 credential_name、scripts/import_credentials.py 完全对齐，下次同步时
session_manager.acquire 据此取用）。不在 server 触发浏览器验证——server 容器无 chromium，
登录态由 worker collect 时自然建立并写入 login_sessions。
GET：读 login_sessions 表，反映 worker 上次建立/校验的会话状态（可能为 none）。
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from inboxserver.api.auth import require_api_key
from inboxserver.api.deps import get_session
from inboxserver.infrastructure.persistence.crypto.vault import CredentialVault
from inboxserver.infrastructure.persistence.repositories.credential import CredentialRepo
from inboxserver.infrastructure.persistence.repositories.login_session import LoginSessionRepo

router = APIRouter(tags=["login"])

log = structlog.get_logger(__name__)

# 各 cookie 类代登录平台的必填凭据字段（与 LoginStrategy.requires_credentials 对齐）。
# inoreader/youtube 是 session 类（多 cookie storage_state），走 import_credentials.py，不在此 API。
_COOKIE_FIELDS: dict[str, str] = {
    "zhihu": "z_c0",
    "bilibili": "sessdata",
}


@router.post("/login/{platform}/cookie")
async def write_cookie(
    platform: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    payload: Annotated[dict[str, str], Body()],
    _: Annotated[None, Depends(require_api_key)],
) -> dict:
    """写入代登录 cookie 凭据（Fernet 加密落库，幂等 upsert）。"""
    field = _COOKIE_FIELDS.get(platform)
    if field is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unsupported platform: {platform}（支持 cookie 类: {list(_COOKIE_FIELDS)}）",
        )
    value = payload.get(field)
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"缺少必填字段: {field}",
        )
    vault = CredentialVault()
    repo = CredentialRepo(session)
    name = f"{platform}_creds"
    await repo.upsert(name, platform, "cookie", vault.encrypt({field: value}))
    # 审计日志：脱敏只记 platform + vault_id，绝不记录凭据值
    log.info("credential_written", platform=platform, vault_id=name)
    return {
        "status": "ok",
        "platform": platform,
        "vault_id": name,
        "note": "凭据已存，登录态将在下次同步时由 worker 建立",
    }


@router.get("/login/{platform}/status")
async def login_status(
    platform: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    _: Annotated[None, Depends(require_api_key)],
) -> dict:
    """查询 platform 当前登录态（读 login_sessions 表，由 worker collect 时建立）。"""
    row = await LoginSessionRepo(session).get(platform)
    if row is None:
        return {
            "status": "ok",
            "platform": platform,
            "session_status": "none",
            "note": "尚未建立登录会话（需先同步触发 worker 登录）",
        }
    return {
        "status": "ok",
        "platform": platform,
        "session_status": row.status,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        "last_used_at": row.last_used_at.isoformat() if row.last_used_at else None,
        "last_error": row.last_error,
    }
