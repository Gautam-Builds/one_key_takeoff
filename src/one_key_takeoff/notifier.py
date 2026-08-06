from typing import Protocol

import httpx

from .config import settings
from .logger import get_logger

logger = get_logger()


class NotificationService(Protocol):
    async def send_notification(self, recipient: str, message: str) -> None: ...


class WhapiNotifier:
    """Whapi HTTP WhatsApp notification service implementation."""

    def __init__(self, token: str | None = None):
        self.token = token or settings.whapi_token

    async def send_notification(self, recipient: str, message: str) -> None:
        if not self.token or recipient.startswith("test_"):
            logger.info(f"[Notifier Log] Recipient [{recipient}]: {message}")
            return

        url = "https://panel.whapi.cloud/api/messages/text"
        headers = {
            "Authorization": f"Bearer {self.token.strip()}",
            "Content-Type": "application/json",
        }
        payload = {"typing_time": 0, "to": recipient, "body": message}

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                if response.status_code in (200, 201):
                    logger.info(f"Notification sent to {recipient}: {message}")
                else:
                    logger.error(
                        f"Failed to send notification to {recipient}. HTTP {response.status_code}: {response.text}"
                    )
        except Exception:
            logger.exception(f"HTTP error while sending notification to {recipient}")


# Default notifier instance
default_notifier = WhapiNotifier()


async def send_whatsapp_message(chat_id: str, text: str):
    """Convenience function for backward compatibility."""
    await default_notifier.send_notification(chat_id, text)
