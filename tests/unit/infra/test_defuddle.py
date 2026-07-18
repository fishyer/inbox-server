"""Python → Node Defuddle 子进程边界测试。"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

import inboxserver.infrastructure.article_archive.defuddle as module
from inboxserver.infrastructure.article_archive.defuddle import DefuddleBridge, DefuddleError


class _Process:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.input = b""
        self.killed = False

    async def communicate(self, payload: bytes):
        self.input = payload
        return self.stdout, self.stderr

    def kill(self) -> None:
        self.killed = True

    async def wait(self) -> None:
        return None


async def test_defuddle_bridge_parse_success(monkeypatch, tmp_path) -> None:
    process = _Process(
        json.dumps(
            {
                "ok": True,
                "article": {
                    "title": "文章",
                    "author": "作者",
                    "published_at": "2026-07-15",
                    "markdown": "正文" * 100,
                },
            }
        ).encode()
    )
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    bridge = DefuddleBridge(script_path=tmp_path / "bridge.mjs")

    article = await bridge.parse("https://example.com/a", "<html>ok</html>")

    assert article.title == "文章"
    assert article.author == "作者"
    request = json.loads(process.input)
    assert request["action"] == "parse"
    assert request["url"] == "https://example.com/a"


async def test_defuddle_bridge_render_success(monkeypatch, tmp_path) -> None:
    process = _Process(json.dumps({"ok": True, "markdown": "---\ntitle: x\n---\n正文\n"}).encode())
    monkeypatch.setattr(
        module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    bridge = DefuddleBridge(script_path=tmp_path / "bridge.mjs")

    rendered = await bridge.render(
        {"title": "x", "source_url": "https://example.com", "tags": ["AI"]},
        "正文",
    )

    assert rendered.startswith("---")
    assert json.loads(process.input)["action"] == "render"


async def test_defuddle_bridge_render_removes_standalone_reader_cta_lines(
    monkeypatch, tmp_path
) -> None:
    process = _Process(json.dumps({"ok": True, "markdown": "---\ntitle: x\n---\n正文\n"}).encode())
    monkeypatch.setattr(
        module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    bridge = DefuddleBridge(script_path=tmp_path / "bridge.mjs")

    await bridge.render(
        {"title": "x", "source_url": "https://example.com", "tags": []},
        "正文第一段\n\n在小说阅读器读本章\n\n  去阅读  \n\n我准备去阅读更多资料。",
    )

    forwarded = json.loads(process.input)["markdown"]
    assert "在小说阅读器读本章" not in {line.strip() for line in forwarded.splitlines()}
    assert "去阅读" not in {line.strip() for line in forwarded.splitlines()}
    assert "我准备去阅读更多资料。" in forwarded


async def test_defuddle_bridge_rejects_input_and_output_over_limits(monkeypatch, tmp_path) -> None:
    spawn = AsyncMock()
    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    bridge = DefuddleBridge(
        script_path=tmp_path / "bridge.mjs",
        max_input_bytes=10,
        max_output_bytes=10,
    )

    with pytest.raises(DefuddleError, match="input_too_large"):
        await bridge.parse("https://example.com", "x" * 100)
    spawn.assert_not_awaited()

    process = _Process(b"x" * 100)
    spawn.return_value = process
    bridge = DefuddleBridge(
        script_path=tmp_path / "bridge.mjs",
        max_input_bytes=10_000,
        max_output_bytes=10,
    )
    with pytest.raises(DefuddleError, match="output_too_large"):
        await bridge.parse("https://example.com", "ok")


@pytest.mark.parametrize(
    ("stdout", "stderr", "returncode", "reason"),
    [
        (b"not-json", b"", 0, "invalid_json"),
        (b"", b"private html and password", 1, "process_failed"),
        (json.dumps({"ok": False, "error": "parse_failed"}).encode(), b"", 0, "parse_failed"),
    ],
)
async def test_defuddle_bridge_maps_process_errors_without_leaking_input(
    monkeypatch,
    tmp_path,
    stdout,
    stderr,
    returncode,
    reason,
) -> None:
    process = _Process(stdout, stderr, returncode)
    monkeypatch.setattr(
        module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    bridge = DefuddleBridge(script_path=tmp_path / "bridge.mjs")

    with pytest.raises(DefuddleError, match=reason) as captured:
        await bridge.parse("https://example.com", "private html and password")

    assert "private html" not in str(captured.value)
    assert "password" not in str(captured.value)


async def test_defuddle_bridge_timeout_kills_process(monkeypatch, tmp_path) -> None:
    class _HangingProcess(_Process):
        async def communicate(self, payload: bytes):
            await asyncio.Event().wait()

    process = _HangingProcess(b"")
    monkeypatch.setattr(
        module.asyncio,
        "create_subprocess_exec",
        AsyncMock(return_value=process),
    )
    bridge = DefuddleBridge(script_path=tmp_path / "bridge.mjs", timeout_seconds=0.001)

    with pytest.raises(DefuddleError, match="timeout"):
        await bridge.parse("https://example.com", "ok")

    assert process.killed is True
