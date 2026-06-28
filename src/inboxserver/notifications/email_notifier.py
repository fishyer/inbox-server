"""邮件通知器（smtplib 直连 QQ SMTP）。

弃用 agently-cli（容器内无 node 依赖，PATH 硬编码 /opt/homebrew 也是坏味道），
改用 Python stdlib smtplib 直连。失败不抛（通知是附加通道，不阻塞主流程）；
凭据缺失时由调用方（scheduler）跳过，本类内部也兜底跳过。
"""

from __future__ import annotations

import asyncio
import smtplib
from email.mime.text import MIMEText

import structlog

from inboxserver.config.settings import settings

_log = structlog.get_logger(__name__)


class EmailNotifier:
    """smtplib 发邮件到 QQ 邮箱（SMTP over SSL）。"""

    def __init__(self):
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._user = settings.smtp_user
        self._pass = settings.smtp_pass
        # 发件人缺省回退 smtp_user（QQ 邮箱发件人需与登录账号一致）
        self._from = settings.email_from or settings.smtp_user
        self._to = settings.email_to

    async def notify(self, message: str, subject: str = "[收件箱同步]") -> None:
        """smtplib 发送（to_thread 包异步，不阻塞 event loop）。凭据缺失/失败均不抛。"""
        if not self._user or not self._pass:
            _log.warning("email_notifier_skip", reason="smtp 凭据缺失")
            return
        try:
            await asyncio.to_thread(self._send, message, subject)
        except Exception as e:
            # SMTP 连接/认证/发送任一失败：不阻塞主流程，仅告警
            _log.warning("email_notify_failed", error=repr(e))

    def _send(self, message: str, subject: str) -> None:
        """同步发送（在 to_thread 里跑，避免阻塞 asyncio loop）。"""
        msg = MIMEText(message, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self._from
        msg["To"] = self._to
        # QQ SMTP over SSL（465）；用 with 保证连接关闭
        with smtplib.SMTP_SSL(self._host, self._port, timeout=30) as s:
            s.login(self._user, self._pass)
            s.sendmail(self._from, [self._to], msg.as_string())
        _log.info("email_notify_sent", to=self._to)
