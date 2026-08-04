from fastapi import FastAPI
from pydantic import BaseModel

from .config import settings
from .logger import logger

# Initialize the FastAPI app
app = FastAPI(title="One Key Takeoff PoC")

# Define what a basic incoming webhook payload looks like for testing
class TestPayload(BaseModel):
    message: str

@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting API in {settings.app_env} mode.")

@app.get("/health")
async def health_check():
    """Endpoint to verify the server is running."""
    logger.info("Health check requested")
    return {"status": "ok", "environment": settings.app_env}

@app.post("/webhook")
async def receive_webhook(payload: TestPayload):
    """Generic webhook endpoint for initial testing."""
    logger.info(f"Received webhook message: {payload.message}")
    return {"status": "success", "received": payload.message}


    