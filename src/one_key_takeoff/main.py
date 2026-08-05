from contextlib import asynccontextmanager

import uvicorn
from fastapi import BackgroundTasks, FastAPI

from .config import settings
from .logger import get_logger
from .mission import execute_mission
from .notifier import NotificationService, default_notifier
from .schemas import WebhookPayload

logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting One Key Takeoff API in {settings.app_env} mode (Host: {settings.host}:{settings.port}).")
    yield
    logger.info("Shutting down API server.")


app = FastAPI(title="One Key Takeoff PoC", lifespan=lifespan)


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "environment": settings.app_env,
        "drone_connection": settings.drone_connection_string
    }


@app.post("/webhook/{event_type}")
async def receive_webhook(event_type: str, payload: WebhookPayload, background_tasks: BackgroundTasks, notifier: NotificationService = default_notifier):
    if event_type == "messages":
        for msg in payload.messages:
            if msg.from_me:
                continue

            sender = msg.chat_id

            if msg.location is not None:
                lat = msg.location.latitude
                lon = msg.location.longitude
                logger.info(f"Incoming Location Pin from {sender}: lat={lat}, lon={lon}")

                # Dispatch background mission task
                background_tasks.add_task(execute_mission, sender, lat, lon)
                logger.info("Mission task dispatched to background worker pool.")

            elif msg.text is not None:
                body = msg.text.body.strip()
                logger.info(f"Incoming Text from {sender}: {body}")

                if body.lower() == "start":
                    await notifier.send_notification(sender, "Welcome to Robothrize Systems. Please send a location pin to initiate a drone mission.")

    return {"status": "success"}


def start():
    """CLI entrypoint for starting the uvicorn server."""
    uvicorn.run("one_key_takeoff.main:app", host=settings.host, port=settings.port, reload=True)