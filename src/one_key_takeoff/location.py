import re
import httpx
from typing import Tuple, Optional
from .logger import get_logger

logger = get_logger()

MAPS_URL_PATTERN = re.compile(
    r"(https?://(?:maps\.app\.goo\.gl|goo\.gl/maps|www\.google\.com/maps|maps\.google\.com)[^\s]+)"
)

def extract_url_from_text(text: str) -> Optional[str]:
    """Finds a Google Maps URL in a block of text."""
    match = MAPS_URL_PATTERN.search(text)
    return match.group(1) if match else None

async def resolve_maps_url(url: str) -> Optional[Tuple[float, float]]:
    """Follows a Maps redirect and extracts lat/lon from the final URL."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            response = await client.get(url)
            final_url = str(response.url)

        # 1. Look for @lat,lon pattern
        match_at = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", final_url)
        if match_at:
            return float(match_at.group(1)), float(match_at.group(2))

        # 2. Look for q=lat,lon pattern
        match_q = re.search(r"[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)", final_url)
        if match_q:
            return float(match_q.group(1)), float(match_q.group(2))

        # 3. Look for /place/lat,lon/ pattern
        match_place = re.search(r"/place/(-?\d+\.\d+),(-?\d+\.\d+)", final_url)
        if match_place:
            return float(match_place.group(1)), float(match_place.group(2))

        return None

    except Exception as e:
        logger.error(f"Error resolving Maps URL ({url}): {e}")
        raise