from contextlib import asynccontextmanager

import uvicorn
from fastapi import BackgroundTasks, FastAPI

from .config import settings
from .logger import get_logger
from .mission import execute_mission
from .notifier import default_notifier, MissionReporter
from .schemas import WebhookPayload
from .location import extract_url_from_text, resolve_maps_url

logger = get_logger()

async def process_url_and_execute(chat_id: str, url: str):
    """Background task orchestrator for URL processing."""
    reporter = MissionReporter(chat_id, default_notifier)
    await reporter.notify_extracting_url()

    try:
        coords = await resolve_maps_url(url)
        if coords:
            lat, lon = coords
            logger.info(f"Successfully extracted coordinates: {lat}, {lon}")
            await execute_mission(chat_id, lat, lon, default_notifier)
        else:
            await reporter.notify_invalid_url()
    except Exception:
        await reporter.notify_url_error()



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
        "drone_connection": settings.drone_connection_string,
    }


@app.post("/webhook")
@app.post("/webhook/{event_type}")
async def receive_webhook(
    payload: WebhookPayload,
    background_tasks: BackgroundTasks,
    event_type: str | None = "messages",
):
    if event_type == "messages" or event_type is None:
        for msg in payload.messages:
            if msg.from_me:
                continue

            sender = msg.chat_id
            reporter = MissionReporter(sender, default_notifier)

            if msg.location is not None:
                lat, lon = msg.location.latitude, msg.location.longitude
                logger.info(f"Incoming Location Pin from {sender}: lat={lat}, lon={lon}")
                background_tasks.add_task(execute_mission, sender, lat, lon)

                logger.info("Mission task dispatched to background worker pool.")

            elif msg.text is not None:
                body = msg.text.body.strip()
                logger.info(f"Incoming Text from {sender}: {body}")

                url = extract_url_from_text(body)

                if url:
                    logger.info(f"Incoming Maps URL from {sender}: {url}")
                    background_tasks.add_task(process_url_and_execute, sender, url)
                elif body.lower() == "start":
                    background_tasks.add_task(reporter.notify_welcome)

    return {"status": "success"}


def start():
    uvicorn.run("one_key_takeoff.main:app", host=settings.host, port=settings.port, reload=True)
