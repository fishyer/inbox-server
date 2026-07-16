"""坚果云 WebDAV 通用适配器：存在检查、目录创建和文件上传。"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path, PurePosixPath


class WebDavError(RuntimeError):
    """WebDAV 操作失败；消息只含稳定错误码，不含凭据。"""


def normalize_remote_path(remote_path: str) -> str:
    """规范化绝对 POSIX 远端路径并拒绝目录穿越。"""
    raw_parts = remote_path.split("/")
    if not remote_path.startswith("/") or ".." in raw_parts:
        raise WebDavError("unsafe_remote_path")
    normalized = str(PurePosixPath(remote_path))
    if normalized == "." or not normalized.startswith("/"):
        raise WebDavError("unsafe_remote_path")
    return normalized


class JianguoyunWebDav:
    """对同步 webdavclient3 的异步安全包装。"""

    def __init__(self, config: dict, *, client=None) -> None:
        if client is not None:
            self._client = client
        else:
            from webdav3.client import Client as WebdavClient

            self._client = WebdavClient(
                {
                    "webdav_hostname": config.get(
                        "base_url", "https://dav.jianguoyun.com/dav"
                    ),
                    "webdav_login": config["webdav_user"],
                    "webdav_password": config["webdav_pass"],
                }
            )

    async def exists(self, remote_path: str) -> bool:
        """检查完整远端路径是否存在。"""
        remote = normalize_remote_path(remote_path)
        try:
            return bool(await asyncio.to_thread(self._client.check, remote))
        except Exception as error:
            raise WebDavError("exists_failed") from error

    async def ensure_directory(self, remote_path: str) -> None:
        """确保远端目录存在；避免坚果云根目录 PROPFIND 与 recursive 检查冲突。"""
        remote = normalize_remote_path(remote_path)
        if await self.exists(remote):
            return
        try:
            await asyncio.to_thread(self._client.mkdir, remote, recursive=False)
        except Exception:
            # 坚果云会对父目录 PROPFIND 返回 403；webdavclient3.mkdir 因此前置失败。
            # 直接发送 MKCOL 仍可成功，且继续复用 client 的认证、超时和状态码处理。
            try:
                from webdav3.urn import Urn

                await asyncio.to_thread(
                    self._client.execute_request,
                    action="mkdir",
                    path=Urn(remote, directory=True).quote(),
                )
            except Exception as error:
                raise WebDavError("mkdir_failed") from error

    async def upload_file(
        self,
        remote_path: str,
        local_path: str,
        *,
        ensure_parent: bool = True,
    ) -> None:
        """上传本地文件；文章归档默认先确保父目录存在。"""
        remote = normalize_remote_path(remote_path)
        if ensure_parent:
            await self.ensure_directory(str(PurePosixPath(remote).parent))
        try:
            await asyncio.to_thread(self._client.upload_file, remote, local_path)
        except Exception as error:
            raise WebDavError("upload_failed") from error

    async def upload_bytes(self, remote_path: str, content: bytes) -> None:
        """经临时文件上传非空字节，并无条件清理临时文件。"""
        if not content:
            raise WebDavError("empty_content")
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix="inbox-article-", suffix=".md", delete=False
            ) as temp:
                temp.write(content)
                temp_path = Path(temp.name)
            try:
                await self.upload_file(remote_path, str(temp_path))
            except WebDavError:
                # 坚果云对 requests 文件流 PUT 返回 403，但同一路径字节 PUT 可正常写入。
                # 保留临时文件流程用于统一清理，再以受限的 Markdown 字节执行兼容上传。
                try:
                    from webdav3.urn import Urn

                    remote = normalize_remote_path(remote_path)
                    await asyncio.to_thread(
                        self._client.execute_request,
                        action="upload",
                        path=Urn(remote).quote(),
                        data=content,
                    )
                except Exception as error:
                    raise WebDavError("upload_failed") from error
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
