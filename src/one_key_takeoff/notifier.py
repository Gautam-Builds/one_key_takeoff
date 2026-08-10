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


class MissionReporter:
    """Handles UX and abstracts message formatting away from the mission logic."""
    def __init__(self, chat_id: str, notifier: NotificationService = default_notifier):
        self.chat_id = chat_id
        self.notifier = notifier


    async def notify_welcome(self):
        await self.notifier.send_notification(self.chat_id, "Welcome to Rovonize Systems. Please send a location pin or a Google Maps link to initiate a drone mission.")

    async def notify_extracting_url(self):
        await self.notifier.send_notification(self.chat_id, "🔄 Extracting coordinates from Google Maps link...")

    async def notify_invalid_url(self):
        await self.notifier.send_notification(self.chat_id, "❌ Could not extract coordinates from that link. Please try sending a native WhatsApp location pin.")

    async def notify_url_error(self):
        await self.notifier.send_notification(self.chat_id, "🚨 Error processing the Google Maps link. Please send a native location pin.")

    async def notify_queued(self):
        await self.notifier.send_notification(self.chat_id, "⚠️ Drone is currently executing another mission. Request queued/rejected.")

    async def notify_geofence_violation(self, distance: float, max_dist: float):
        await self.notifier.send_notification(self.chat_id, f"❌ Target is {distance:.1f}m away, exceeding the max geofence of {max_dist:.0f}m. Aborting.")

    async def notify_accepted(self, distance: float):
        await self.notifier.send_notification(self.chat_id, f"✅ Mission Accepted! Target is {distance:.1f}m away. Finding nearest drone...")

    async def notify_takeoff(self):
        await self.notifier.send_notification(self.chat_id, "🚁 Drone acquired and armed. Taking off...")

    async def notify_arrival(self, distance: float, circle_alt: float):
        await self.notifier.send_notification(self.chat_id, f"📍 Target reached (within {distance:.1f}m)! Descending to {circle_alt}m and initiating surveillance orbit.")

    async def notify_rtl(self):
        await self.notifier.send_notification(self.chat_id, "🏠 Surveillance complete. Returning to launch position (RTL).")

    async def notify_error(self):
        await self.notifier.send_notification(self.chat_id, "🚨 Mission Error: Triggering emergency fail-safe procedure.")