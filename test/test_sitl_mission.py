import asyncio

import pytest

from one_key_takeoff.config import settings
from one_key_takeoff.logger import get_logger
from one_key_takeoff.mission import execute_mission

logger = get_logger("test_sitl_mission")


@pytest.mark.anyio
async def test_sitl_mission_execution():
    conn_str = settings.drone_connection_string
    home_lat = settings.home_lat
    home_lon = settings.home_lon

    # Target: ~100m North of configured Home
    target_lat = home_lat + 0.0009
    target_lon = home_lon

    logger.info(f"Executing closed-loop autonomous mission test on SITL ({conn_str})...")
    await execute_mission("test_chat_123", target_lat, target_lon)
    logger.info("SUCCESS: Closed-loop SITL mission completed cleanly!")


if __name__ == "__main__":
    asyncio.run(test_sitl_mission_execution())
