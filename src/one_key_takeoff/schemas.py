from typing import List, Optional
from pydantic import BaseModel, Field, ConfigDict

class LinkPreview(BaseModel):
    url: str
    body: Optional[str] = None
    title: Optional[str] = None

class LocationData(BaseModel):
    latitude: float = Field(..., description="Latitude in decimal degrees")
    longitude: float = Field(..., description="Longitude in decimal degrees")

class TextData(BaseModel):
    body: str = ""

class MessageItem(BaseModel):
    chat_id: str = "Unknown"
    from_me: bool = False
    text: TextData | None = None
    type: str = ""

    location: LocationData | None = None

    link_preview: Optional[LinkPreview] = None

    model_config = ConfigDict(populate_by_name=True)

class WebhookPayload(BaseModel):
    messages: list[MessageItem] = []
