import asyncio
import pytest

from one_key_takeoff.config import settings
from one_key_takeoff.logger import get_logger
from one_key_takeoff.telemetry import DroneController

logger = get_logger("test_connection")


@pytest.mark.anyio
async def test_drone_connection():
    logger.info(f"Testing drone connection on {settings.drone_connection_string} (baud: {settings.drone_baudrate})...")
    with DroneController() as drone:
        assert drone.master is not None
        logger.info(
            f"SUCCESS! Heartbeat received from System {drone.master.target_system} "
            f"Component {drone.master.target_component}"
        )


if __name__ == "__main__":
    asyncio.run(test_drone_connection())