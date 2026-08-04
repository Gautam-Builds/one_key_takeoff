import asyncio
from geopy.distance import geodesic
from .telemetry import DroneController
from .logger import logger

# We'll use the coordinates you just received as your physical location / Home!
HOME_LAT = 9.9816 
HOME_LON = 76.2999
MAX_DISTANCE_METERS = 20000

# A lock prevents two WhatsApp messages from starting two missions simultaneously
mission_lock = asyncio.Lock()

async def execute_mission(target_lat: float, target_lon: float):
    # Only allow one mission at a time
    if mission_lock.locked():
        logger.warning("Drone is currently busy. Rejecting new mission.")
        return

    async with mission_lock:
        # Geofence Validation
        distance = geodesic((HOME_LAT, HOME_LON), (target_lat, target_lon)).meters
        if distance > MAX_DISTANCE_METERS:
            logger.error(f"Target is {distance:.1f}m away. Exceeds {MAX_DISTANCE_METERS}m geofence! Aborting.")
            return

        logger.info(f"Target validated. Distance: {distance:.1f}m. Starting mission.")
        
        try:
            # Connect to the local SITL simulation (TCP 5760 is the default)
            # In Phase 6, we will change this to /dev/ttyUSB0 for the real RDK X5
            drone = DroneController("tcp:127.0.0.1:5760")
            
            # Phase 1: Takeoff
            drone.arm_and_takeoff(15.0)
            await asyncio.sleep(10) # Wait 10 seconds for altitude climb
            
            # Phase 2: Navigate
            drone.fly_to(target_lat, target_lon, 15.0)
            await asyncio.sleep(15) # Wait 15 seconds for transit
            
            # Phase 3: Hover
            logger.info("Target reached. Hovering...")
            await asyncio.sleep(5)
            
            # Phase 4: Return
            drone.rtl()
            logger.info("Mission sequence complete. Awaiting landing.")
            
        except Exception as e:
            logger.error(f"Mission failed: {str(e)}")