"""通过受限 JSON 标准输入输出调用仓库内 Node.js Defuddle 桥接器。"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from inboxserver.domain.policy.article_archive import DefuddleArticle

DEFAULT_BRIDGE_PATH = Path(__file__).parents[4] / "scripts/article-archive.mjs"
_SAFE_ERROR = re.compile(r"^[a-z0-9_]{1,64}$")


class DefuddleError(RuntimeError):
    """Defuddle 子进程边界错误；消息只含稳定错误码，不含 HTML。"""


class DefuddleBridge:
    """异步 Node.js 桥接器，限制执行时间和标准输入输出大小。"""

    def __init__(
        self,
        *,
        script_path: Path = DEFAULT_BRIDGE_PATH,
        node_binary: str = "node",
        timeout_seconds: float = 30,
        max_input_bytes: int = 8_000_000,
        max_output_bytes: int = 10_000_000,
    ) -> None:
        self._script_path = script_path
        self._node_binary = node_binary
        self._timeout_seconds = timeout_seconds
        self._max_input_bytes = max_input_bytes
        self._max_output_bytes = max_output_bytes

    async def parse(self, url: str, html: str) -> DefuddleArticle:
        """解析 HTML 为结构化文章。"""
        result = await self._run({"action": "parse", "url": url, "html": html})
        article = result.get("article")
        if not isinstance(article, dict):
            raise DefuddleError("invalid_article")
        return DefuddleArticle(
            title=str(article.get("title") or "").strip(),
            author=str(article.get("author") or "").strip(),
            published_at=str(article.get("published_at") or "").strip(),
            markdown=str(article.get("markdown") or "").strip(),
        )

    async def render(self, metadata: dict, markdown: str) -> str:
        """使用 Eta 模板渲染稳定 Obsidian Properties 与正文。"""
        result = await self._run(
            {"action": "render", "metadata": metadata, "markdown": markdown}
        )
        rendered = result.get("markdown")
        if not isinstance(rendered, str) or not rendered.strip():
            raise DefuddleError("invalid_markdown")
        return rendered

    async def _run(self, request: dict) -> dict:
        payload = json.dumps(request, ensure_ascii=False).encode()
        if len(payload) > self._max_input_bytes:
            raise DefuddleError("input_too_large")
        process = await asyncio.create_subprocess_exec(
            self._node_binary,
            str(self._script_path),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(payload),
                timeout=self._timeout_seconds,
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise DefuddleError("timeout") from error
        if process.returncode != 0:
            raise DefuddleError("process_failed")
        if len(stdout) > self._max_output_bytes:
            raise DefuddleError("output_too_large")
        try:
            response = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DefuddleError("invalid_json") from error
        if not isinstance(response, dict):
            raise DefuddleError("invalid_response")
        if response.get("ok") is not True:
            code = str(response.get("error") or "bridge_failed")
            raise DefuddleError(code if _SAFE_ERROR.fullmatch(code) else "bridge_failed")
        return response
