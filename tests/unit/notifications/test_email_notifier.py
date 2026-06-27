"""EmailNotifier 测试：smtplib 发送 + 凭据缺失跳过 + 失败不抛。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from inboxserver.notifications import email_notifier as en


async def test_notify_sends_via_smtp(monkeypatch):
    """凭据齐全 → 调 SMTP_SSL.login + sendmail"""
    monkeypatch.setattr(en.settings, "smtp_user", "u@qq.com")
    monkeypatch.setattr(en.settings, "smtp_pass", "pass")
    monkeypatch.setattr(en.settings, "smtp_host", "smtp.qq.com")
    monkeypatch.setattr(en.settings, "smtp_port", 465)
    monkeypatch.setattr(en.settings, "email_from", "")
    monkeypatch.setattr(en.settings, "email_to", "to@qq.com")

    with patch("inboxserver.notifications.email_notifier.smtplib.SMTP_SSL") as mock_smtp:
        instance = MagicMock()
        mock_smtp.return_value.__enter__.return_value = instance
        n = en.EmailNotifier()
        await n.notify("报告内容", subject="测试")

    mock_smtp.assert_called_once_with("smtp.qq.com", 465, timeout=30)
    instance.login.assert_called_once_with("u@qq.com", "pass")
    assert instance.sendmail.called


async def test_notify_skip_no_credentials(monkeypatch):
    """凭据缺失 → 跳过，不调 smtplib"""
    monkeypatch.setattr(en.settings, "smtp_user", "")
    monkeypatch.setattr(en.settings, "smtp_pass", "")

    with patch("inboxserver.notifications.email_notifier.smtplib.SMTP_SSL") as mock_smtp:
        n = en.EmailNotifier()
        await n.notify("报告")  # 不抛即通过

    mock_smtp.assert_not_called()


async def test_notify_failure_no_raise(monkeypatch):
    """smtplib 异常 → 不抛（附加通道，仅告警）"""
    monkeypatch.setattr(en.settings, "smtp_user", "u@qq.com")
    monkeypatch.setattr(en.settings, "smtp_pass", "pass")

    with patch(
        "inboxserver.notifications.email_notifier.smtplib.SMTP_SSL",
        side_effect=Exception("connection refused"),
    ):
        n = en.EmailNotifier()
        await n.notify("报告")  # 不抛即通过
