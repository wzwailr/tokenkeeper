"""tokenkeeper 告警通知模块。

支持:
- Webhook（Slack / 钉钉 / 飞书 / 企业微信兼容）
- 预算超限时自动推送

用法::

    from tokenkeeper.alerting import AlertManager

    alerts = AlertManager()
    alerts.add_webhook("https://hooks.slack.com/...")
    alerts.send("预算超限: 本月已花费 $50")

    # 或直接配置环境变量:
    export TOKENKEEPER_WEBHOOK_URL=https://hooks.slack.com/...
    export TOKENKEEPER_WEBHOOK2_URL=https://oapi.dingtalk.com/robot/...
"""

from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

__all__ = ["AlertManager", "send_alert"]


@dataclass
class AlertManager:
    """告警管理器。

    支持多个 webhook URL，并发发送。

    Args:
        webhook_urls: webhook URL 列表（也可通过环境变量 TOKENKEEPER_WEBHOOK_URL 设置）
        prefix: 消息前缀
    """

    webhook_urls: list[str] = field(default_factory=list)
    prefix: str = "[tokenkeeper]"

    def __post_init__(self) -> None:
        # 从环境变量加载
        env_url = os.environ.get("TOKENKEEPER_WEBHOOK_URL")
        if env_url and env_url not in self.webhook_urls:
            self.webhook_urls.append(env_url)
        # 支持多个 webhook: TOKENKEEPER_WEBHOOK2_URL, TOKENKEEPER_WEBHOOK3_URL ...
        for i in range(2, 10):
            url = os.environ.get(f"TOKENKEEPER_WEBHOOK{i}_URL")
            if url and url not in self.webhook_urls:
                self.webhook_urls.append(url)

    def add_webhook(self, url: str) -> None:
        """添加 webhook URL。"""
        if url not in self.webhook_urls:
            self.webhook_urls.append(url)

    def send(self, message: str, level: str = "warning") -> None:
        """发送告警到所有 webhook。

        Args:
            message: 告警消息
            level: 告警级别（info / warning / error）
        """
        if not self.webhook_urls:
            logger.debug("无 webhook 配置，跳过告警")
            return

        payload = self._build_payload(message, level)

        def _post(url: str) -> None:
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                urllib.request.urlopen(req, timeout=5)
                logger.debug("告警已发送: %s", url)
            except Exception as e:
                logger.error("发送告警失败 (%s): %s", url, e)

        threads = []
        for url in self.webhook_urls:
            t = threading.Thread(target=_post, args=(url,))
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=10)

    @staticmethod
    def _build_payload(message: str, level: str) -> dict:
        """构建 webhook payload（兼容 Slack / 钉钉 / 飞书）。"""
        emoji = {"info": "ℹ️", "warning": "⚠️", "error": "🚨"}.get(level, "⚠️")

        return {
            "text": f"{emoji} {message}",
            # Slack 格式
            "attachments": [{
                "color": {"info": "good", "warning": "warning", "error": "danger"}.get(level, "warning"),
                "text": message,
            }],
            # 钉钉 markdown 格式
            "msgtype": "markdown",
            "markdown": {
                "title": "tokenkeeper 告警",
                "text": f"### {emoji} tokenkeeper 告警\n\n{message}",
            },
        }


# 全局实例
_alerts = AlertManager()


def send_alert(message: str, level: str = "warning") -> None:
    """快捷发送告警（使用全局 AlertManager）。

    环境变量配置::

        TOKENKEEPER_WEBHOOK_URL=https://hooks.slack.com/xxx
    """
    _alerts.send(message, level)
