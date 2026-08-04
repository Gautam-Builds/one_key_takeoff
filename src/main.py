from fastapi import FastAPI, Request, BackgroundTasks
from .config import settings
from .logger import logger
from .mission import execute_mission

app = FastAPI(title="One Key Takeoff PoC")

@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting API in {settings.app_env} mode.")

@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.app_env}

@app.post("/webhook/{event_type}")
async def receive_webhook(event_type: str, request: Request, background_tasks: BackgroundTasks):
    payload = await request.json()
    
    if event_type == "messages":
        if "messages" in payload and len(payload["messages"]) > 0:
            msg = payload["messages"][0]
            
            if msg.get("from_me"):
                return {"status": "ignored"}
                
            sender = msg.get("chat_id", "Unknown")
            
            if "text" in msg:
                body = msg["text"].get("body", "").strip()
                logger.info(f"--- Incoming Text from {sender}: {body}")
                
            elif "location" in msg:
                lat = msg["location"].get("latitude")
                lon = msg["location"].get("longitude")
                logger.info(f"--- Incoming Location Pin from {sender}: {lat}, {lon}")
                
                # TRIGGER THE DRONE MISSION HERE IN THE BACKGROUND
                background_tasks.add_task(execute_mission, lat, lon)
                logger.info("Mission task dispatched to drone!")

    return {"status": "success"}