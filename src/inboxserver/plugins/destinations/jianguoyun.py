"""坚果云目的地插件。

WebDAV PUT 到 {base_path}/{remote_name}，Basic Auth。
（来自 inbox_sync.upload_to_webdav）。webdav3 client 同步，用 asyncio.to_thread 包装。
webdav_client 可注入（测试 mock）；不传则内部延迟 import webdav3.client。
"""

from __future__ import annotations

from inboxserver.domain.models import ItemKind
from inboxserver.infrastructure.destinations.webdav import JianguoyunWebDav
from inboxserver.plugins.contracts import DispatchOutcome


class JianguoyunDestination:
    name = "jianguoyun"
    item_kind = ItemKind.FILE
    required_config = ["webdav_user", "webdav_pass"]

    def __init__(self, config: dict, webdav_client=None):
        self._base_path = config.get("base_path", "/我的坚果云")
        self._webdav = JianguoyunWebDav(config, client=webdav_client)

    async def dispatch(self, item: dict) -> tuple[bool, DispatchOutcome]:
        local_path = item["local_path"]
        remote = f"{self._base_path}/{item['remote_name']}"
        try:
            await self._webdav.upload_file(remote, local_path, ensure_parent=False)
            return True, DispatchOutcome.OK
        except Exception:
            return False, DispatchOutcome.FAIL
