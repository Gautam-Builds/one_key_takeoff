from pydantic import BaseModel, ConfigDict, Field


class LinkPreview(BaseModel):
    url: str
    body: str | None = None
    title: str | None = None


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

    link_preview: LinkPreview | None = None

    model_config = ConfigDict(populate_by_name=True)


class WebhookPayload(BaseModel):
    messages: list[MessageItem] = []
