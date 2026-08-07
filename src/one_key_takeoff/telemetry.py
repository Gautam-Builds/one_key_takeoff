import time
from typing import Any

import serial
from geopy.distance import geodesic
from pymavlink import mavutil
from pymavlink.dialects.v20 import ardupilotmega as mavlink

from .config import settings
from .logger import get_logger

logger = get_logger()

# MAVLink position control mask constant (ignore velocity, acceleration, yaw)
POSITION_CONTROL_MASK = 0b0000111111111000


class DroneController:
    """MAVLink vehicle controller wrapper for ArduPilot flight controllers."""

    def __init__(
        self,
        connection_string: str | None = None,
        baudrate: int | None = None,
        timeout: int | None = None,
    ):
        self.connection_string = connection_string or settings.drone_connection_string
        self.baudrate = baudrate or settings.drone_baudrate
        self.timeout = timeout or settings.drone_connection_timeout
        # self.master: mavutil.mavfile | None = None
        self.master: Any = None

        self.connect()

    def connect(self):
        """Establishes MAVLink connection with hard retries for flaky USB buses."""
        retry_delay = 2.0  # Seconds to wait between hard retries

        for attempt in range(settings.connection_max_retries):
            logger.info(
                f"Connecting to flight controller at {self.connection_string} (Attempt {attempt}/{settings.connection_max_retries})..."
            )

            try:
                self.master = mavutil.mavlink_connection(
                    self.connection_string, baud=self.baudrate, autoreconnect=True
                )

                # Wait for the first heartbeat
                hb = self.master.wait_heartbeat(timeout=self.timeout)

                if hb is None or self.master.target_system == 0:
                    raise TimeoutError("Heartbeat timeout.")

                logger.info(
                    f"✅ Heartbeat received! Connected to System {self.master.target_system}, Component {self.master.target_component}"
                )

                # Connection successful, request data and exit the retry loop
                self.request_data_streams(4)
                return

            except Exception as e:
                logger.warning(f"Connection attempt {attempt} failed: {e}")

                # Ensure the broken serial port is closed before trying again
                if self.master:
                    self.master.close()

                if attempt < settings.connection_max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error(
                        f"❌ Failed to connect to drone after {settings.connection_max_retries} attempts."
                    )
                    raise  # Pass the error up so the mission aborts cleanly

    def close(self):
        """Closes the MAVLink connection cleanly."""
        if self.master:
            logger.info("Closing MAVLink connection...")
            try:
                self.master.close()
            except (OSError, AttributeError) as e:
                logger.warning(f"Error while closing connection: {e}")
            finally:
                self.master = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def request_data_streams(self, rate_hz: int = 4):
        """Requests MAVLink telemetry data streams from flight controller."""
        if not self.master:
            return
        logger.info(f"Requesting MAVLink telemetry data streams at {rate_hz} Hz...")
        try:
            self.master.mav.request_data_stream_send(
                self.master.target_system,
                self.master.target_component,
                mavlink.MAV_DATA_STREAM_ALL,
                rate_hz,
                1,
            )
        except (OSError, AttributeError) as e:
            logger.warning(f"Could not request data streams: {e}")

    def drain_messages(self, timeout: float = 0.1):
        """Drains STATUSTEXT and warning messages from the MAVLink buffer."""
        if not self.master:
            return
        start = time.time()
        while time.time() - start < timeout:
            msg = self.master.recv_match(
                type=["STATUSTEXT", "SYS_STATUS"], blocking=False
            )
            if not msg:
                break
            if msg.get_type() == "STATUSTEXT":
                logger.info(f"Flight Controller Message: {msg.text}")

    def check_prearm_messages(self):
        """Fetches and logs any pending STATUSTEXT messages from ArduPilot."""
        if not self.master:
            return
        logger.info("Checking ArduPilot status messages...")
        while True:
            # blocking=False ensures it doesn't freeze your script if the queue is empty
            msg = self.master.recv_match(type="STATUSTEXT", blocking=False)
            if not msg:
                break  # Queue is empty

            # Clean up the text (pymavlink sometimes returns bytes instead of strings)
            text = msg.text
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="ignore")

            # Log it as a WARNING so it stands out in your terminal
            logger.warning(f"🚁 ArduPilot: {text}")

    def verify_prearm_checks(self, timeout: float = 5.0) -> bool:
        """Verifies GPS lock (3D Fix) and monitors STATUSTEXT for pre-arm errors."""
        if not self.master:
            return False

        logger.info("Running pre-arm checks (GPS lock, System status)...")
        self.check_prearm_messages()
        start = time.time()
        gps_fix_ok = False

        while time.time() - start < timeout:
            msg = self.master.recv_match(
                type=["GPS_RAW_INT", "STATUSTEXT", "SYS_STATUS"],
                blocking=True,
                timeout=1.0,
            )
            if not msg:
                continue

            msg_type = msg.get_type()
            if msg_type == "STATUSTEXT":
                text = msg.text
                if isinstance(text, bytes):
                    text = text.decode("utf-8", errors="ignore")
                logger.warning(f"🚁 ArduPilot: {text}")
            elif msg_type == "GPS_RAW_INT":
                fix_type = getattr(msg, "fix_type", 0)
                satellites = getattr(msg, "satellites_visible", 0)
                logger.info(f"GPS Status: fix_type={fix_type}, satellites={satellites}")
                if fix_type >= 3:
                    gps_fix_ok = True
                    break

        if not gps_fix_ok:
            logger.warning(
                "GPS 3D Fix not yet confirmed. Pre-arm check warning issued."
            )
        return gps_fix_ok

    def get_gps_location(self, timeout: float = 10.0) -> tuple[float, float]:
        """Retrieves home/current GPS latitude and longitude from the flight controller."""

        if not self.master:
            try:
                self.connect()
            except Exception as e:
                logger.error(f"Initial connection check failed: {e}")

        logger.info("Fetching GPS coordinates from flight controller...")
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                if (
                    hasattr(self.master, "port")
                    and self.master.port
                    and not self.master.port.isOpen()
                ):
                    raise serial.SerialException("Serial port is closed.")

                msg = self.master.recv_match(
                    type=["GLOBAL_POSITION_INT", "GPS_RAW_INT", "HOME_POSITION"],
                    blocking=True,
                    timeout=1.0,
                )
                if msg:
                    msg_type = msg.get_type()
                    lat_raw = getattr(msg, "lat", getattr(msg, "latitude", 0))
                    lon_raw = getattr(msg, "lon", getattr(msg, "longitude", 0))
                    if lat_raw != 0 or lon_raw != 0:
                        lat = lat_raw / 1e7
                        lon = lon_raw / 1e7
                        logger.info(
                            f"Retrieved GPS coordinates via {msg_type}: lat={lat:.7f}, lon={lon:.7f}"
                        )
                        return (lat, lon)

            except (serial.SerialException, AttributeError, Exception) as e:
                logger.warning(
                    f"Serial port disconnected during GPS fetch ({e}). Attempting auto-reconnect..."
                )
                try:
                    self.connect()
                except Exception as conn_err:
                    logger.error(f"Auto-reconnect failed: {conn_err}")
                    time.sleep(1.0)

        if settings.home_lat is not None and settings.home_lon is not None:
            logger.warning(
                f"Could not read valid GPS from drone within {timeout}s. "
                f"Falling back to configured home location: ({settings.home_lat}, {settings.home_lon})"
            )
            return (settings.home_lat, settings.home_lon)

        raise TimeoutError(
            f"Could not obtain valid GPS coordinates from drone within {timeout}s."
        )

    def set_mode(self, mode: str):
        """Sets flight mode (e.g. GUIDED, RTL, LAND)."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        mode_mapping = self.master.mode_mapping()

        if mode_mapping is None:
            raise RuntimeError(
                "Mode mapping is not available. Has a heartbeat been received?"
            )

        if mode not in mode_mapping:
            raise ValueError(
                f"Unknown flight mode: {mode}. Available: {list(mode_mapping.keys())}"
            )

        mode_id = mode_mapping[mode]
        self.master.mav.set_mode_send(
            self.master.target_system,
            mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_id,
        )
        logger.info(f"Flight mode command sent: {mode} (ID: {mode_id})")

    def wait_until_armed(self, timeout: float = 30.0):
        """Closed-loop wait until vehicle motors report armed status."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        logger.info(f"Waiting for motors to arm (timeout: {timeout}s)...")
        start_time = time.time()
        last_arm_cmd_time = 0.0

        while time.time() - start_time < timeout:
            msg = self.master.recv_match(
                type=["HEARTBEAT", "STATUSTEXT", "COMMAND_ACK"],
                blocking=True,
                timeout=1.0,
            )
            if msg:
                msg_type = msg.get_type()
                if msg_type == "STATUSTEXT":
                    logger.info(f"FC StatusText: {msg.text}")
                elif msg_type == "COMMAND_ACK":
                    logger.info(
                        f"Command ACK: command={msg.command}, result={msg.result}"
                    )

            if self.master.motors_armed():
                logger.info("Motors successfully ARMED!")
                return True

            if time.time() - last_arm_cmd_time > 2.0:
                self.master.mav.command_long_send(
                    self.master.target_system,
                    self.master.target_component,
                    mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0,
                    1,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                )
                last_arm_cmd_time = time.time()

        raise TimeoutError(
            f"Arming timed out after {timeout} seconds. Check pre-arm messages / GPS lock."
        )

    def arm_and_takeoff(self, altitude: float, timeout: int | None = None):
        """Runs pre-arm checks, arms motors, and commands takeoff."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        arm_timeout = timeout or settings.drone_arm_timeout

        self.verify_prearm_checks(timeout=3.0)

        self.set_mode("LOITER")
        time.sleep(1.5)

        self.wait_until_armed(timeout=arm_timeout)
        self.set_mode("GUIDED")
        time.sleep(0.5)

        logger.info(f"Sending takeoff command to target altitude {altitude}m...")
        self.master.mav.command_long_send(
            self.master.target_system,
            self.master.target_component,
            mavlink.MAV_CMD_NAV_TAKEOFF,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            altitude,
        )

    def wait_until_altitude(
        self, target_alt: float, tolerance: float = 0.5, timeout: float = 40.0
    ) -> float:
        """Closed-loop verification waiting until drone climbs to target relative altitude."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        self.request_data_streams(4)
        logger.info(
            f"Monitoring takeoff climb to target altitude {target_alt}m (tolerance: +- {tolerance}m)..."
        )
        start_time = time.time()
        last_takeoff_cmd_time = time.time()

        while time.time() - start_time < timeout:
            msg = self.master.recv_match(
                type=["GLOBAL_POSITION_INT", "VFR_HUD", "STATUSTEXT", "COMMAND_ACK"],
                blocking=True,
                timeout=1.0,
            )
            if not msg:
                continue

            msg_type = msg.get_type()
            if msg_type == "STATUSTEXT":
                logger.info(f"FC StatusText: {msg.text}")
                continue
            elif msg_type == "COMMAND_ACK":
                logger.info(f"Command ACK: cmd={msg.command}, result={msg.result}")
                continue

            rel_alt = 0.0
            if msg_type == "GLOBAL_POSITION_INT":
                rel_alt = msg.relative_alt / 1000.0
            # elif msg_type == "VFR_HUD":
            #     rel_alt = getattr(msg, "alt", 0.0)

            logger.info(
                f"Climb Telemetry: Relative Alt = {rel_alt:.2f}m / Target = {target_alt}m"
            )
            if rel_alt >= (target_alt - tolerance):
                logger.info(f"Target altitude reached! Current alt: {rel_alt:.2f}m")
                return rel_alt

            # Re-send TAKEOFF command if vehicle hasn't started ascending after 4 seconds
            if rel_alt < 0.5 and (time.time() - last_takeoff_cmd_time > 4.0):
                logger.info(
                    f"Re-sending Takeoff command to target altitude {target_alt}m..."
                )
                self.master.mav.command_long_send(
                    self.master.target_system,
                    self.master.target_component,
                    mavlink.MAV_CMD_NAV_TAKEOFF,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    target_alt,
                )
                last_takeoff_cmd_time = time.time()

        raise TimeoutError(f"Takeoff climb timed out after {timeout} seconds.")

    def fly_to(self, lat: float, lon: float, alt: float):
        """Commands drone to navigate to global latitude/longitude coordinates."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        logger.info(f"Navigating to coordinate target: ({lat}, {lon}) at {alt}m...")
        self.master.mav.set_position_target_global_int_send(
            0,
            self.master.target_system,
            self.master.target_component,
            mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            POSITION_CONTROL_MASK,
            int(lat * 1e7),
            int(lon * 1e7),
            alt,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )

    def wait_until_reached_location(
        self,
        target_lat: float,
        target_lon: float,
        alt: float,
        acceptance_radius: float = 2.5,
        timeout: float = 60.0,
    ) -> float:
        """Closed-loop monitoring until vehicle reaches within acceptance_radius of target coordinate."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        target_pos = (target_lat, target_lon)
        logger.info(
            f"Monitoring navigation to ({target_lat}, {target_lon}) within {acceptance_radius}m..."
        )
        start_time = time.time()
        last_cmd_time = 0.0

        while time.time() - start_time < timeout:
            if time.time() - last_cmd_time > 5.0:
                self.fly_to(target_lat, target_lon, alt)
                last_cmd_time = time.time()

            msg = self.master.recv_match(
                type=["GLOBAL_POSITION_INT", "STATUSTEXT"], blocking=True, timeout=1.0
            )
            if not msg:
                continue

            if msg.get_type() == "STATUSTEXT":
                logger.info(f"FC StatusText: {msg.text}")
                continue

            current_lat = msg.lat / 1e7
            current_lon = msg.lon / 1e7
            current_pos = (current_lat, current_lon)

            dist = geodesic(current_pos, target_pos).meters
            logger.info(
                f"Navigation Telemetry: Current Pos ({current_lat:.7f}, {current_lon:.7f}), Distance to Target = {dist:.1f}m"
            )

            if dist <= acceptance_radius:
                logger.info(f"Target position reached! Final distance: {dist:.1f}m")
                return dist

        raise TimeoutError(f"Navigation timed out after {timeout} seconds.")

    def rtl(self):
        """Commands Return-To-Launch (RTL)."""
        logger.info("Commanding Return-To-Launch (RTL)...")
        self.set_mode("RTL")

    def land(self):
        """Commands LAND flight mode for emergency landing."""
        logger.info("Commanding Emergency LAND mode...")
        self.set_mode("LAND")
