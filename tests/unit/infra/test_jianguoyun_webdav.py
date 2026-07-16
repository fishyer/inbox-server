"""可复用坚果云 WebDAV 适配器测试。"""

from __future__ import annotations

from pathlib import Path

import pytest

from inboxserver.infrastructure.destinations.webdav import JianguoyunWebDav, WebDavError


class _Client:
    def __init__(self):
        self.existing: set[str] = set()
        self.checked: list[str] = []
        self.created: list[tuple[str, bool]] = []
        self.uploaded: list[tuple[str, bytes, str]] = []

    def check(self, remote_path):
        self.checked.append(remote_path)
        return remote_path in self.existing

    def mkdir(self, remote_path, recursive=False):
        self.created.append((remote_path, recursive))
        self.existing.add(remote_path)

    def upload_file(self, remote_path, local_path):
        self.uploaded.append((remote_path, Path(local_path).read_bytes(), local_path))


async def test_webdav_exists_checks_full_path() -> None:
    client = _Client()
    client.existing.add("/我的坚果云/文章归档/a.md")
    webdav = JianguoyunWebDav({"webdav_user": "u", "webdav_pass": "p"}, client=client)

    assert await webdav.exists("/我的坚果云/文章归档/a.md") is True
    assert client.checked == ["/我的坚果云/文章归档/a.md"]


async def test_webdav_upload_bytes_creates_parent_and_cleans_temp_file() -> None:
    client = _Client()
    webdav = JianguoyunWebDav({"webdav_user": "u", "webdav_pass": "p"}, client=client)

    content = "# 正文\n".encode()
    await webdav.upload_bytes("/我的坚果云/文章归档/a.md", content)

    assert client.created == [("/我的坚果云/文章归档", False)]
    assert client.uploaded[0][:2] == ("/我的坚果云/文章归档/a.md", content)
    assert Path(client.uploaded[0][2]).exists() is False


async def test_webdav_rejects_empty_content_and_unsafe_path() -> None:
    webdav = JianguoyunWebDav({"webdav_user": "u", "webdav_pass": "p"}, client=_Client())

    with pytest.raises(WebDavError, match="empty_content"):
        await webdav.upload_bytes("/我的坚果云/文章归档/a.md", b"")
    with pytest.raises(WebDavError, match="unsafe_remote_path"):
        await webdav.exists("/我的坚果云/../secret")


async def test_webdav_directory_creation_bypasses_jianguoyun_parent_check() -> None:
    class _ParentCheckFailClient(_Client):
        def mkdir(self, remote_path, recursive=False):
            raise RuntimeError("parent PROPFIND forbidden")

        def execute_request(self, *, action, path):
            self.direct_request = (action, path)
            return object()

    client = _ParentCheckFailClient()
    webdav = JianguoyunWebDav({"webdav_user": "u", "webdav_pass": "p"}, client=client)

    await webdav.ensure_directory("/我的坚果云/文章归档")

    assert client.direct_request[0] == "mkdir"
    assert "%E6%88%91%E7%9A%84%E5%9D%9A%E6%9E%9C%E4%BA%91" in client.direct_request[1]


async def test_webdav_upload_bytes_falls_back_from_file_stream_to_bytes() -> None:
    class _StreamForbiddenClient(_Client):
        def upload_file(self, remote_path, local_path):
            raise RuntimeError("stream PUT forbidden")

        def execute_request(self, *, action, path, data):
            self.direct_upload = (action, path, data)
            return object()

    client = _StreamForbiddenClient()
    client.existing.add("/我的坚果云/文章归档")
    webdav = JianguoyunWebDav({"webdav_user": "u", "webdav_pass": "p"}, client=client)

    await webdav.upload_bytes("/我的坚果云/文章归档/a.md", "正文".encode())

    assert client.direct_upload[0] == "upload"
    assert client.direct_upload[2] == "正文".encode()


async def test_webdav_error_does_not_leak_credentials() -> None:
    class _FailingClient(_Client):
        def check(self, remote_path):
            raise RuntimeError("user-secret pass-secret")

    webdav = JianguoyunWebDav(
        {"webdav_user": "user-secret", "webdav_pass": "pass-secret"},
        client=_FailingClient(),
    )

    with pytest.raises(WebDavError, match="exists_failed") as captured:
        await webdav.exists("/我的坚果云/文章归档/a.md")

    assert "user-secret" not in str(captured.value)
    assert "pass-secret" not in str(captured.value)
