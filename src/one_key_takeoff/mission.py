import asyncio

from geopy.distance import geodesic

from .config import settings
from .logger import get_logger
from .notifier import NotificationService, default_notifier
from .telemetry import DroneController

logger = get_logger()
mission_lock = asyncio.Lock()


async def execute_mission(
    chat_id: str,
    target_lat: float,
    target_lon: float,
    notifier: NotificationService = default_notifier,
):
    """Executes closed-loop mission sequence using telemetry verification."""
    if mission_lock.locked():
        await notifier.send_notification(
            chat_id,
            "⚠️ Drone is currently executing another mission. Request queued/rejected.",
        )
        return

    async with mission_lock:
        drone: DroneController | None = None
        try:
            # 1. Connect to drone
            logger.info(f"Connecting to flight controller for mission ({chat_id})...")
            drone = await asyncio.to_thread(DroneController)

            # 2. Retrieve dynamic home / initial vehicle position
            initial_pos = await asyncio.to_thread(drone.get_gps_location, 10.0)
            target_pos = (target_lat, target_lon)

            # 3. Dynamic Geofence check
            distance = geodesic(initial_pos, target_pos).meters
            if distance > settings.max_geofence_meters:
                msg = (
                    f"❌ Target is {distance:.1f}m away. "
                    f"Exceeds max geofence of {settings.max_geofence_meters:.0f}m. Aborting mission."
                )
                logger.warning(msg)
                await notifier.send_notification(chat_id, msg)
                return

            logger.info(
                f"Starting mission for {chat_id}. Target: ({target_lat}, {target_lon}), Distance: {distance:.1f}m"
            )
            await notifier.send_notification(
                chat_id,
                f"✅ Mission Accepted! Target is {distance:.1f}m away. Finding nearest drone....",
            )

            # 4. Arm and initiate takeoff
            takeoff_alt = settings.takeoff_altitude_meters
            logger.info(f"Arming and initiating takeoff to {takeoff_alt}m...")
            await notifier.send_notification(
                chat_id,
                "🚁 Nearest drone acquired. Taking off ....",
            )
            await asyncio.to_thread(drone.arm_and_takeoff, takeoff_alt)

            # 5. Closed-loop Altitude Verification
            logger.info(f"Waiting for drone to reach target altitude {takeoff_alt}m...")
            achieved_alt = await asyncio.to_thread(
                drone.wait_until_altitude, takeoff_alt, 0.5, 40.0
            )
            # await notifier.send_notification(
            #     chat_id,
            #     f"Altitude reached ({achieved_alt:.1f}m). Navigating to coordinates...",
            # )

            # 6. Command navigation and Closed-loop Waypoint Reach Verification
            logger.info(f"Flying to target ({target_lat}, {target_lon})...")
            await asyncio.to_thread(drone.fly_to, target_lat, target_lon, takeoff_alt)

            # Calculate dynamic navigation timeout based on distance (min 5 m/s speed + 60s buffer)
            nav_timeout = max(60.0, (distance / 5.0) + 60.0)
            logger.info(
                f"Monitoring navigation to target (Timeout: {nav_timeout:.1f}s for {distance:.1f}m)..."
            )

            final_dist = await asyncio.to_thread(
                drone.wait_until_reached_location,
                target_lat,
                target_lon,
                takeoff_alt,
                3.0,
                nav_timeout,
            )

            # 7. Target Hover (5s intentional hover)
            await notifier.send_notification(
                chat_id,
                f"📍 Target reached (within {final_dist:.1f}m)! Hovering for {settings.hover_time_seconds} seconds...",
            )
            await asyncio.sleep(settings.hover_time_seconds)

            # 8. Return to Launch (RTL)
            logger.info("Executing Return to Launch (RTL)...")
            await asyncio.to_thread(drone.rtl)
            await notifier.send_notification(
                chat_id, "🏠 Mission complete. Returning to launch position."
            )

        except Exception:
            logger.exception("Mission failed unexpectedly")
            await notifier.send_notification(
                chat_id, "🚨 Mission Error: Triggering fail-safe procedure."
            )

            # Emergency Fallback Ladder: RTL -> LAND
            if drone and drone.master:
                try:
                    logger.warning("Attempting fail-safe RTL command...")
                    await asyncio.to_thread(drone.rtl)
                except Exception as rtl_err:  # noqa: BLE001
                    logger.error(
                        f"Failed to issue fail-safe RTL: {rtl_err}. Triggering LAND mode..."
                    )
                    try:
                        await asyncio.to_thread(drone.land)
                    except Exception as land_err:  # noqa: BLE001
                        logger.critical(f"Critical Fail-safe failure: {land_err}")

        finally:
            if drone:
                await asyncio.to_thread(drone.close)
