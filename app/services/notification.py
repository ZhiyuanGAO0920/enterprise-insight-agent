"""V4 通知服务。

支持邮件发送和 webhook 通知（企业微信/钉钉/飞书）。
目前实现邮件通道，webhook 通道预留接口。
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

from app.logging_config import get_logger

logger = get_logger("eia.services.notification")


class EmailChannel:
    """邮件通知通道。

    使用 SMTP 发送邮件，支持 PDF 附件。
    """

    def __init__(
        self,
        smtp_host: str = "smtp.example.com",
        smtp_port: int = 587,
        username: str = "",
        password: str = "",
        use_tls: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_tls = use_tls

    async def send(
        self,
        to_email: str,
        subject: str,
        body: str,
        from_name: str = "企业智能分析平台",
        attachments: list[tuple[str, bytes, str]] | None = None,
    ) -> bool:
        """发送邮件。

        Args:
            to_email: 收件人邮箱。
            subject: 邮件主题。
            body: HTML 正文。
            from_name: 发件人名称。
            attachments: [(文件名, 内容bytes, MIME类型), ...]

        Returns:
            发送成功返回 True。
        """
        try:
            msg = MIMEMultipart("mixed")
            msg["Subject"] = subject
            msg["From"] = f"{from_name} <{self.username}>"
            msg["To"] = to_email

            msg.attach(MIMEText(body, "html", "utf-8"))

            if attachments:
                for filename, content, mime_type in attachments:
                    part = MIMEBase(*mime_type.split("/", 1))
                    part.set_payload(content)
                    encoders.encode_base64(part)
                    part.add_header(
                        "Content-Disposition",
                        f'attachment; filename="{filename}"',
                    )
                    msg.attach(part)

            # SMTP 发送使用同步 API，在 asyncio 中通过线程池执行
            import asyncio
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                self._send_sync,
                msg,
                to_email,
            )

            logger.info("邮件已发送", to=to_email, subject=subject)
            return True
        except Exception as e:
            logger.error("邮件发送失败", to=to_email, error=str(e), exc_info=True)
            return False

    def _send_sync(self, msg: MIMEMultipart, to_email: str) -> None:
        """同步 SMTP 发送。"""
        if self.use_tls:
            server = smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=30)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, timeout=30)

        try:
            if self.username and self.password:
                server.login(self.username, self.password)
            server.sendmail(self.username, to_email, msg.as_string())
        finally:
            server.quit()


# ============================================================================
# V4.1: Webhook 通知通道（飞书/钉钉/企业微信）
# ============================================================================

class WebhookChannel:
    """Webhook 通知通道，支持飞书/钉钉/企业微信三种平台。

    通过 POST JSON 到 webhook URL 发送消息，消息格式按平台自动适配。
    """

    def __init__(self, webhook_url: str, platform: str = "dingtalk"):
        self.webhook_url = webhook_url
        self.platform = platform  # "feishu" | "dingtalk" | "wecom"

    async def send(self, title: str, content: str) -> bool:
        """发送消息到 webhook。

        Args:
            title: 消息标题（钉钉/企微用；飞书卡片标题）。
            content: Markdown 内容。

        Returns:
            发送成功返回 True。
        """
        if self.platform == "feishu":
            payload = self._build_feishu_payload(title, content)
        elif self.platform == "wecom":
            payload = self._build_wecom_payload(content)
        else:
            payload = self._build_dingtalk_payload(title, content)

        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(self.webhook_url, json=payload)
                if resp.status_code < 400:
                    logger.info("Webhook sent", platform=self.platform)
                    return True
                logger.warning("Webhook failed", platform=self.platform, status=resp.status_code)
                return False
        except Exception as e:
            logger.error("Webhook error", platform=self.platform, error=str(e))
            return False

    @staticmethod
    def _build_dingtalk_payload(title: str, text: str) -> dict:
        return {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
        }

    @staticmethod
    def _build_wecom_payload(text: str) -> dict:
        return {
            "msgtype": "markdown",
            "markdown": {"content": text},
        }

    @staticmethod
    def _build_feishu_payload(title: str, text: str) -> dict:
        # 飞书消息卡片格式：标题 + Markdown 正文
        # 长文本自动折叠
        return {
            "msg_type": "interactive",
            "card": {
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": text[:8000],  # 飞书单卡片 8000 字符限制
                    }
                ],
            },
        }


# ============================================================================
# V4.1: 统一通知发送入口
# ============================================================================

async def send_notification(title: str, content: str) -> dict[str, bool]:
    """向所有已配置的 webhook 通道发送通知。

    读取 config 中的 webhook URL，仅向非空 URL 发送。
    各通道独立发送，一个失败不影响其他。

    Args:
        title: 消息标题。
        content: Markdown 消息正文。

    Returns:
        {"feishu": True/False, "dingtalk": True/False, "wecom": True/False}
    """
    from app.config import get_settings
    settings = get_settings()

    channels = [
        ("feishu", settings.feishu_webhook_url),
        ("dingtalk", settings.dingtalk_webhook_url),
        ("wecom", settings.wecom_webhook_url),
    ]

    results: dict[str, bool] = {}
    for platform, url in channels:
        if not url:
            results[platform] = False
            continue
        ch = WebhookChannel(url, platform=platform)
        results[platform] = await ch.send(title, content)

    return results
