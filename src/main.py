from fastapi import FastAPI, Request
from .config import settings
from .logger import logger

app = FastAPI(title="One Key Takeoff PoC")

@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting API in {settings.app_env} mode.")

@app.get("/health")
async def health_check():
    return {"status": "ok", "environment": settings.app_env}

# Updated path to handle Whapi's "Path" mode (e.g., /webhook/messages)
@app.post("/webhook/{event_type}")
async def receive_webhook(event_type: str, request: Request):
    """Webhook endpoint for Whapi JSON payloads."""
    payload = await request.json()
    
    logger.info(f"Received webhook event type: {event_type}")
    
    # Handle incoming messages
    if event_type == "messages":
        if "messages" in payload and len(payload["messages"]) > 0:
            msg = payload["messages"][0]
            
            # Ignore messages sent BY the bot itself
            if msg.get("from_me"):
                return {"status": "ignored"}
                
            sender = msg.get("chat_id", "Unknown")
            
            # Check if it's a standard text message
            if "text" in msg:
                body = msg["text"].get("body", "").strip()
                logger.info("--- Incoming WhatsApp Message ---")
                logger.info(f"Sender: {sender}")
                logger.info(f"Text: {body}")
                
            # # Check if it's a Location Pin
            # elif "location" in msg:
            #     lat = msg["location"].get("lat")
            #     lon = msg["location"].get("lon")
            #     logger.info("--- Incoming WhatsApp Location Pin ---")
            #     logger.info(f"Sender: {sender}")
            #     logger.info(f"Coordinates: {lat}, {lon}")

            elif "location" in msg:
                lat = msg["location"].get("latitude")
                lon = msg["location"].get("longitude")
                logger.info("--- Incoming WhatsApp Location Pin ---")
                logger.info(f"Sender: {sender}")
                logger.info(f"Coordinates: {lat}, {lon}")
                
    elif event_type == "statuses":
        logger.info("Received a message status update (delivered, read, etc.)")
        # You can process statuses here if needed later

    return {"status": "success"}