import asyncio

from geopy.distance import geodesic

from .config import settings
from .logger import get_logger
from .notifier import NotificationService, default_notifier, MissionReporter
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
    reporter = MissionReporter(chat_id, notifier)

    if mission_lock.locked():
        await reporter.notify_queued()
        return

    async with mission_lock:
        drone: DroneController | None = None
        try:
            # 1. Connect & Geofence Check
            logger.info(f"Connecting to flight controller for mission ({chat_id})...")
            drone = await asyncio.to_thread(DroneController)

            initial_pos = await asyncio.to_thread(drone.get_gps_location, 10.0)
            target_pos = (target_lat, target_lon)

            distance = geodesic(initial_pos, target_pos).meters

            if distance > settings.max_geofence_meters:
                logger.warning (f"❌ Target is {distance:.1f}m away. " f"Exceeds max geofence of {settings.max_geofence_meters:.0f}m.")
                await reporter.notify_geofence_violation(distance, settings.max_geofence_meters)
                return

            logger.info(f"Starting mission for {chat_id}. Target: ({target_lat}, {target_lon}), Distance: {distance:.1f}m")
            await reporter.notify_accepted(distance)

            # 2. Takeoff
            takeoff_alt = settings.takeoff_altitude_meters

            logger.info(f"Arming and initiating takeoff to {takeoff_alt}m...")
            await reporter.notify_takeoff()

            await asyncio.to_thread(drone.arm_and_takeoff, takeoff_alt)

            # Closed-loop Altitude Verification
            logger.info(f"Waiting for drone to reach target altitude {takeoff_alt}m...")
            await asyncio.to_thread(drone.wait_until_altitude, takeoff_alt, 0.5, 40.00)
            logger.info(f"Altitude reached: {takeoff_alt:.1f}m")

            # 3. Navigate to Target
            logger.info(f"Flying to target ({target_lat}, {target_lon})...")
            nav_timeout = max(60.0, (distance / 5.0) + 60.0)
            logger.info(f"Monitoring navigation to target (Timeout: {nav_timeout:.1f}s for {distance:.1f}m)...")

            await asyncio.to_thread(drone.fly_to, target_lat, target_lon, takeoff_alt)

            final_dist = await asyncio.to_thread(
                drone.wait_until_reached_location,
                target_lat,
                target_lon,
                takeoff_alt,
                3.0,
                nav_timeout,
            )

            # 4. Perform Orbit / Circle Mode
            circle_alt = settings.orbit_altitude_meters
            await reporter.notify_arrival(final_dist, circle_alt)

            # Command the descent
            logger.info(f"Descending to {circle_alt}m for orbit...")
            await asyncio.to_thread(drone.change_altitude, circle_alt, target_lat, target_lon)

            # Wait for the drone to physically reach the lower altitude
            await asyncio.to_thread(drone.wait_until_altitude, circle_alt)

            # 5. Orbit (Circle Mode)
            await asyncio.to_thread(drone.perform_target_action)

            # 6. Return to Launch (RTL)
            logger.info("Orbit complete. Executing RTL...")
            await asyncio.to_thread(drone.rtl)
            await reporter.notify_rtl()

        except BaseException as exc:
            if isinstance(exc, asyncio.CancelledError):
                logger.warning("Mission task was cancelled!")
            else:
                logger.exception("Mission failed unexpectedly")

            await reporter.notify_error()

            # Emergency Fallback Ladder: RTL -> LAND
            if drone and getattr(drone, "master", None):
                try:
                    logger.warning("Attempting fail-safe RTL command...")
                    await asyncio.to_thread(drone.rtl)
                    await reporter.notify_rtl()
                except Exception as rtl_err:  # noqa: BLE001
                    logger.error(
                        f"Failed to issue fail-safe RTL: {rtl_err}. Triggering LAND mode..."
                    )
                    try:
                        await asyncio.to_thread(drone.land)
                    except Exception as land_err:  # noqa: BLE001
                        logger.critical(f"Critical Fail-safe failure: {land_err}")

            if isinstance(exc, asyncio.CancelledError):
                raise

        finally:
            if drone:
                await asyncio.to_thread(drone.close)

