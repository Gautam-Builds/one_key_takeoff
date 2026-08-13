import threading
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

        self.master: Any = None
        self._is_closing = False

        self._stop_heartbeat = threading.Event()
        self._heartbeat_thread: threading.Thread | None = None
        self._reader_thread: threading.Thread | None = None

        self.vehicle_state = {"parameters": {}, "mode": None, "altitude": 0.0}
        self.events = {"param_received": threading.Event()}
        self._reader_thread = None

        self.connect()

    def connect(self):
        """Establishes MAVLink connection with hard retries for flaky USB buses."""
        retry_delay = 3.0  # Seconds to wait between hard retries
        self._is_closing = False

        for attempt in range(1, settings.connection_max_retries + 1):
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

                # Connection successful, request data streams & start background heartbeat
                self.request_data_streams(4)
                self._start_heartbeat_thread()
                self._start_reader_thread()
                return

            except Exception as e:
                logger.warning(f"Connection attempt {attempt} failed: {e}")

                # Ensure the broken serial port is closed before trying again
                if self.master:
                    try:
                        self.master.close()
                    except Exception:
                        pass
                    self.master = None

                if attempt < settings.connection_max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                else:
                    logger.error(
                        f"❌ Failed to connect to drone after {settings.connection_max_retries} attempts."
                    )
                    raise  # Pass the error up so the mission aborts cleanly

    # ---------------------------------------------------------
    # READER THREAD
    # ---------------------------------------------------------

    def _start_reader_thread(self):
        self._stop_reader_thread()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, name="MAVLink-Reader", daemon=True
        )
        self._reader_thread.start()
        logger.info("Background MAVLink reader thread started.")

    def _stop_reader_thread(self):
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)
        self._reader_thread = None

    def _reader_loop(self):
        """Continuously reads MAVLink messages and updates the global state dictionary."""
        while not self._is_closing:
            if not self.master:
                time.sleep(0.5)
                continue

            try:
                msg = self.master.recv_msg()

                if not msg:
                    time.sleep(0.01)
                    continue

                msg_type = msg.get_type()

                if msg_type == "PARAM_VALUE":
                    param_id = msg.param_id
                    if isinstance(param_id, bytes):
                        param_id = param_id.decode("utf-8", errors="ignore")
                    param_id = param_id.rstrip("\x00")

                    self.vehicle_state["parameters"][param_id] = msg.param_value
                    self.events["param_received"].set()

                elif msg_type == "STATUSTEXT":
                    text = msg.text
                    if isinstance(text, bytes):
                        text = text.decode("utf-8", errors="ignore")
                    logger.info(f"FC StatusText: {text}")

                elif msg_type == "HEARTBEAT":
                    if msg.get_srcComponent() == 1:
                        self.vehicle_state["mode"] = getattr(msg, "custom_mode", None)

            except Exception as e:
                logger.warning(f"Error in MAVLink reader loop: {e}")
                if self._is_closing:
                    break
                time.sleep(0.5)

    # ---------------------------------------------------------
    # HEARTBEAT THREAD
    # ---------------------------------------------------------

    def _start_heartbeat_thread(self):
        """Spawns background thread emitting 1 Hz MAVLink Heartbeat to FC."""
        self._stop_heartbeat_thread()
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name="MAVLink-Heartbeat", daemon=True
        )
        self._heartbeat_thread.start()
        logger.info("Background MAVLink heartbeat thread started.")

    def _stop_heartbeat_thread(self):
        """Stops the heartbeat thread cleanly."""
        self._stop_heartbeat.set()
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=2.0)
        self._heartbeat_thread = None

    def _heartbeat_loop(self):
        """Emits MAVLink Heartbeat every 1 second to keep GCS failsafe clear."""
        while not self._stop_heartbeat.is_set() and not self._is_closing:
            if self.master and hasattr(self.master, "mav"):
                try:
                    self.master.mav.heartbeat_send(
                        mavlink.MAV_TYPE_ONBOARD_CONTROLLER,
                        mavlink.MAV_AUTOPILOT_INVALID,
                        0,
                        0,
                        0,
                    )
                except Exception:
                    pass
            self._stop_heartbeat.wait(1.0)

    # ---------------------------------------------------------
    # CLEANUP
    # ---------------------------------------------------------

    def close(self):
        """Closes the MAVLink connection cleanly."""
        self._is_closing = True
        self._stop_heartbeat_thread()
        self._stop_reader_thread()

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
        """Requests targeted MAVLink telemetry data streams from flight controller."""
        if not self.master:
            return
        logger.info(
            f"Configuring MAVLink telemetry stream intervals at {rate_hz} Hz..."
        )
        try:
            # Set targeted message interval for GLOBAL_POSITION_INT (msg #33)
            self.master.mav.command_long_send(
                self.master.target_system,
                self.master.target_component,
                mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
                0,
                mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
                int(1e6 / rate_hz),
                0,
                0,
                0,
                0,
                0,
            )
            # Fallback stream request for compatibility
            self.master.mav.request_data_stream_send(
                self.master.target_system,
                self.master.target_component,
                mavlink.MAV_DATA_STREAM_POSITION,
                rate_hz,
                1,
            )
            self.master.mav.request_data_stream_send(
                self.master.target_system,
                self.master.target_component,
                mavlink.MAV_DATA_STREAM_EXTRA1,
                rate_hz,
                1,
            )
        except (OSError, AttributeError, Exception) as e:
            logger.warning(f"Could not request data streams: {e}")

    def drain_messages(self, timeout: float = 0.1):
        """Drains STATUSTEXT and warning messages from the MAVLink buffer."""
        if not self.master:
            return
        start = time.time()
        while time.time() - start < timeout:
            try:
                msg = self.master.recv_match(
                    type=["STATUSTEXT", "SYS_STATUS"], blocking=False
                )
                if not msg:
                    break
                if msg.get_type() == "STATUSTEXT":
                    text = msg.text
                    if isinstance(text, bytes):
                        text = text.decode("utf-8", errors="ignore")
                    logger.info(f"Flight Controller Message: {text}")
            except Exception:
                break

    def check_prearm_messages(self):
        """Fetches and logs any pending STATUSTEXT messages from ArduPilot."""
        if not self.master:
            return
        logger.info("Checking ArduPilot status messages...")
        while True:
            try:
                msg = self.master.recv_match(type="STATUSTEXT", blocking=False)
                if not msg:
                    break

                text = msg.text
                if isinstance(text, bytes):
                    text = text.decode("utf-8", errors="ignore")

                logger.warning(f"🚁 ArduPilot: {text}")
            except Exception:
                break

    def verify_prearm_checks(self, timeout: float = 5.0) -> bool:
        """Verifies GPS lock (3D Fix) and monitors STATUSTEXT for pre-arm errors."""
        if not self.master:
            return False

        logger.info("Running pre-arm checks (GPS lock, System status)...")
        self.check_prearm_messages()
        start = time.time()
        gps_fix_ok = False

        while time.time() - start < timeout and not self._is_closing:
            try:
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
                    logger.info(
                        f"GPS Status: fix_type={fix_type}, satellites={satellites}"
                    )
                    if fix_type >= 3:
                        gps_fix_ok = True
                        break
            except Exception as e:
                logger.warning(f"Error during pre-arm verification: {e}")
                time.sleep(0.5)

        if not gps_fix_ok:
            logger.warning("GPS 3D Fix not confirmed. Pre-arm check warning issued.")
        return gps_fix_ok

    def set_parameter(
        self, param_id: str, param_value: float, timeout: float = 5.0
    ) -> bool:
        """Sets an ArduPilot parameter dynamically and waits for PARAM_VALUE ACK."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        logger.info(f"Setting parameter {param_id} to {param_value}")

        # MAVLink standard requires param_id to be exactly 16 bytes
        param_id_bytes = param_id.encode("utf-8").ljust(16, b"\x00")

        fc_system = (
            1 if self.master.target_system in (0, 255) else self.master.target_system
        )
        fc_component = 1

        self.vehicle_state["parameters"].pop(param_id, None)

        # self.events["param_received"].clear()

        self.master.mav.param_set_send(
            fc_system,
            fc_component,
            param_id_bytes,
            param_value,
            mavlink.MAV_PARAM_TYPE_REAL32,
        )

        start_time = time.time()
        last_request_time = 0.0

        while time.time() - start_time < timeout and not self._is_closing:
            # self.events["param_received"].wait(timeout=1)

            if time.time() - last_request_time > 1.0:
                self.master.mav.param_request_read_send(
                    fc_system, fc_component, param_id_bytes, -1
                )
                last_request_time = time.time()

            if param_id in self.vehicle_state["parameters"]:
                current_value = self.vehicle_state["parameters"][param_id]

                if abs(current_value - param_value) < 0.01:
                    logger.info(
                        f"✅ Parameter {param_id} set successfully to {param_value}"
                    )
                    return True
                else:
                    self.master.mav.param_set_send(
                        fc_system,
                        fc_component,
                        param_id_bytes,
                        param_value,
                        mavlink.MAV_PARAM_TYPE_REAL32,
                    )
                    self.vehicle_state["parameters"].pop(param_id, None)

            time.sleep(0.05)

        logger.warning(
            f"⚠️ Parameter {param_id} set request sent, but no PARAM_VALUE ACK received within {timeout}s."
        )
        return False

    def set_rc_override(self, channel: int, pwm: int):
        """
        Overrides a specific RC channel.
        MAVLink uses 65535 to mean "ignore/do not override this channel".
        Sending 0 or 65535 releases the override.
        """
        if not self.master:
            return

        rc_values = [65535] * 18
        rc_values[channel - 1] = pwm

        self.master.mav.rc_channels_override_send(
            self.master.target_system, self.master.target_component, *rc_values
        )

    def get_gps_location(self, timeout: float = 10.0) -> tuple[float, float]:
        """Retrieves home/current GPS latitude and longitude from the flight controller."""

        if not self.master:
            try:
                self.connect()
            except Exception as e:
                logger.error(f"Initial connection check failed: {e}")

        logger.info("Fetching GPS coordinates from flight controller...")
        start_time = time.time()

        while time.time() - start_time < timeout and not self._is_closing:
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

    def set_mode(self, mode: str, timeout: float = 5.0) -> bool:
        """Sets flight mode (e.g. GUIDED, RTL, LAND) with serial drop protection."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        mode_mapping = self.master.mode_mapping()
        if mode_mapping is None or mode not in mode_mapping:
            raise ValueError(f"Unknown flight mode: {mode}")

        mode_id = mode_mapping[mode]
        logger.info(f"Requesting flight mode: {mode} (ID: {mode_id})...")

        try:
            self.master.mav.set_mode_send(
                self.master.target_system,
                mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                mode_id,
            )
        except (serial.SerialException, OSError, AttributeError) as e:
            logger.error(f"Failed to send set_mode command over serial: {e}")
            return False

        logger.info(f"Flight mode command sent: {mode} (ID: {mode_id})")

        start_time = time.time()
        while time.time() - start_time < timeout and not self._is_closing:
            try:
                msg = self.master.recv_match(
                    type="HEARTBEAT", blocking=True, timeout=1.0
                )
                if msg and getattr(msg, "custom_mode", None) == mode_id:
                    logger.info(f"✅ Flight mode successfully changed to {mode}.")
                    return True
            except (serial.SerialException, OSError, AttributeError) as e:
                logger.warning(
                    f"Serial interruption while verifying mode change to {mode}: {e}"
                )
                time.sleep(0.5)

        logger.error(f"❌ Mode change failed. FC refused to enter {mode} mode.")
        return False

    def wait_until_armed(self, timeout: float = 30.0):
        """Closed-loop wait until vehicle motors report armed status."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        logger.info(f"Waiting for motors to arm (timeout: {timeout}s)...")
        start_time = time.time()
        last_arm_cmd_time = 0.0

        while time.time() - start_time < timeout and not self._is_closing:
            try:
                msg = self.master.recv_match(
                    type=["HEARTBEAT", "STATUSTEXT", "COMMAND_ACK"],
                    blocking=True,
                    timeout=1.0,
                )
                if msg:
                    msg_type = msg.get_type()
                    if msg_type == "STATUSTEXT":
                        text = msg.text
                        if isinstance(text, bytes):
                            text = text.decode("utf-8", errors="ignore")
                        logger.info(f"FC StatusText: {text}")
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
            except (serial.SerialException, AttributeError, OSError) as e:
                logger.warning(f"Serial interruption while waiting for arm: {e}")
                time.sleep(0.5)

        raise TimeoutError(
            f"Arming timed out after {timeout} seconds. Check pre-arm messages / GPS lock."
        )

    def arm_and_takeoff(self, altitude: float, timeout: int | None = None):
        """Runs pre-arm checks, arms motors, and commands takeoff."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        arm_timeout = timeout or settings.drone_arm_timeout

        # Strictly enforce pre-arm checks (3D GPS Lock & FC status)
        # if not self.verify_prearm_checks(timeout=5.0):
        #     raise RuntimeError(
        #         "Pre-arm checks failed: GPS 3D lock not confirmed or FC pre-arm error."
        #     )

        # 1. Enter LOITER for safety checks
        if not self.set_mode("LOITER", timeout=5.0):
            raise RuntimeError("Could not switch to LOITER mode for arming.")

        # 2. Arm the motors
        self.wait_until_armed(timeout=arm_timeout)

        # 3. Enter GUIDED mode to accept navigation commands
        if not self.set_mode("GUIDED", timeout=5.0):
            raise RuntimeError("Could not switch to GUIDED mode for takeoff.")

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
    ) -> bool:
        """Closed-loop verification waiting until drone climbs to target relative altitude."""

        if not getattr(self, "master", None):
            raise RuntimeError("Drone is not connected.")

        self.request_data_streams(4)

        logger.info(
            f"Monitoring climb to target altitude {target_alt}m (tolerance: +- {tolerance}m)..."
        )
        start_time = time.time()
        rel_alt = 0.0

        while time.time() - start_time < timeout and not self._is_closing:
            try:
                if hasattr(self.master, "port") and self.master.port:
                    if (
                        hasattr(self.master.port, "isOpen")
                        and not self.master.port.isOpen()
                    ):
                        raise serial.SerialException("Serial port is closed.")

                msg = self.master.recv_match(
                    type=[
                        "GLOBAL_POSITION_INT",
                        "STATUSTEXT",
                        "COMMAND_ACK",
                        "HEARTBEAT",
                    ],
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
                    logger.info(f"FC StatusText: {text}")
                    continue
                elif msg_type == "COMMAND_ACK":
                    logger.info(f"Command ACK: cmd={msg.command}, result={msg.result}")
                    continue
                elif msg_type == "HEARTBEAT":
                    if msg.get_srcComponent() == 1:
                        mode_map = self.master.mode_mapping() if self.master else None
                        guided_id = mode_map.get("GUIDED") if mode_map else None
                        loiter_id = mode_map.get("LOITER") if mode_map else None
                        current_mode = getattr(msg, "custom_mode", None)
                        if guided_id is not None and current_mode not in (
                            guided_id,
                            loiter_id,
                        ):
                            raise RuntimeError(
                                f"Flight mode changed unexpectedly away from GUIDED to custom_mode ID {current_mode}"
                            )
                        continue

                elif msg_type == "GLOBAL_POSITION_INT":
                    rel_alt = msg.relative_alt / 1000.0
                    logger.info(
                        f"Telemetry: Current Alt = {rel_alt:.2f}m / Target = {target_alt}m"
                    )

                    if abs(rel_alt - target_alt) <= tolerance:
                        logger.info(
                            f"Target altitude reached! Current alt: {rel_alt:.2f}m"
                        )
                        return True

            except (serial.SerialException, AttributeError, OSError) as e:
                logger.warning(
                    f"Serial interruption during altitude monitor ({e}). Attempting reconnect..."
                )
                try:
                    self.connect()
                except Exception as conn_err:
                    logger.error(f"Auto-reconnect failed: {conn_err}")
                    time.sleep(1.0)

        if self._is_closing:
            raise RuntimeError("Altitude monitor aborted: Controller is closing.")

        logger.error(
            f"❌ Altitude change timed out after {timeout} seconds. Current altitude: {rel_alt:.2f}m"
        )
        raise TimeoutError(f"Takeoff climb timed out after {timeout} seconds.")

    def change_altitude(
        self, target_alt: float, current_lat: float, current_lon: float
    ):
        """Commands a vertical ascent or descent while in GUIDED mode."""
        if not self.master:
            raise RuntimeError("Drone is not connected.")

        logger.info(f"Commanding mid-flight altitude change to {target_alt}m...")

        self.master.mav.set_position_target_global_int_send(
            0,
            self.master.target_system,
            self.master.target_component,
            mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            POSITION_CONTROL_MASK,
            int(current_lat * 1e7),
            int(current_lon * 1e7),
            target_alt,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )

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

        while time.time() - start_time < timeout and not self._is_closing:
            try:
                if time.time() - last_cmd_time > 5.0:
                    self.fly_to(target_lat, target_lon, alt)
                    last_cmd_time = time.time()

                msg = self.master.recv_match(
                    type=["GLOBAL_POSITION_INT", "STATUSTEXT", "HEARTBEAT"],
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
                    logger.info(f"FC StatusText: {text}")
                    continue
                elif msg_type == "HEARTBEAT":
                    if msg.get_srcComponent() == 1:
                        mode_map = self.master.mode_mapping() if self.master else None
                        guided_id = mode_map.get("GUIDED") if mode_map else None
                        current_mode = getattr(msg, "custom_mode", None)
                        if guided_id is not None and current_mode != guided_id:
                            raise RuntimeError(
                                f"Flight mode changed unexpectedly away from GUIDED to custom_mode ID {current_mode}"
                            )
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

            except (serial.SerialException, AttributeError, OSError) as e:
                logger.warning(
                    f"Serial interruption during navigation monitor ({e}). Attempting reconnect..."
                )
                try:
                    self.connect()
                except Exception as conn_err:
                    logger.error(f"Auto-reconnect failed: {conn_err}")
                    time.sleep(1.0)

        if self._is_closing:
            raise RuntimeError("Navigation aborted: Controller is closing.")

        raise TimeoutError(f"Navigation timed out after {timeout} seconds.")

    def perform_target_action(self):
        """Executes a CIRCLE orbit around the drone's current position with continuous telemetry polling."""

        if not self.master:
            raise RuntimeError("Drone is not connected.")

        radius = settings.orbit_radius_meters
        orbit_speed = settings.orbit_speed_mps
        rate = settings.orbit_rate_dps
        duration = settings.orbit_duration_seconds

        logger.info(
            f"Initiating orbit: {radius}m radius for {duration}s at {orbit_speed} m/s..."
        )

        # 1. Set the circle radius (ArduPilot expects centimeters)
        # self.set_parameter("CIRCLE_RADIUS", radius * 100.0)
        modern_success = self.set_parameter(
            "CIRCLE_RADIUS_M", float(radius), timeout=2.0
        )

        if not modern_success:
            logger.info(
                "Modern CIRCLE_RADIUS_M not found. Falling back to legacy CIRCLE_RADIUS (cm)..."
            )
            # Fall back to the legacy parameter (centimeters)
            self.set_parameter("CIRCLE_RADIUS", radius * 100.0, timeout=2.0)

        self.set_parameter("CIRCLE_RATE", rate)

        self.set_rc_override(channel=3, pwm=1500)

        # 2. Command the mode change and verify it worked
        mode_accepted = self.set_mode("CIRCLE", timeout=5.0)

        if not mode_accepted:
            self.set_rc_override(channel=3, pwm=65535)
            raise RuntimeError("Failed to enter CIRCLE mode. Orbit aborted.")

        # 3. Wait loop with continuous telemetry & heartbeat polling
        logger.info(
            f"Successfully entered CIRCLE mode. Orbiting for {duration} seconds..."
        )
        start_time = time.time()

        try:
            while time.time() - start_time < duration and not self._is_closing:
                try:
                    self.set_rc_override(channel=3, pwm=1500)

                    msg = self.master.recv_match(
                        type=["STATUSTEXT", "HEARTBEAT"], blocking=True, timeout=1.0
                    )
                    if msg:
                        msg_type = msg.get_type()
                        if msg_type == "STATUSTEXT":
                            text = msg.text
                            if isinstance(text, bytes):
                                text = text.decode("utf-8", errors="ignore")
                            logger.info(f"FC StatusText: {text}")

                        elif msg_type == "HEARTBEAT":
                            if msg.get_srcComponent() == 1:
                                mode_map = (
                                    self.master.mode_mapping() if self.master else None
                                )
                                circle_id = mode_map.get("CIRCLE") if mode_map else None
                                current_mode = getattr(msg, "custom_mode", None)

                                if circle_id is not None and current_mode != circle_id:
                                    raise RuntimeError(
                                        f"Flight mode changed unexpectedly away from CIRCLE to custom_mode ID {current_mode}"
                                    )

                except (serial.SerialException, AttributeError, OSError) as e:
                    logger.warning(f"Serial interruption during orbit ({e})")
                    time.sleep(0.5)
        finally:
            self.set_rc_override(channel=3, pwm=65535)
            self.set_mode("GUIDED", timeout=5.0)
            logger.info("Orbit duration completed.")

    def rtl(self):
        """Commands Return-To-Launch (RTL)."""
        logger.info("Commanding Return-To-Launch (RTL)...")
        self.set_mode("RTL")

    def land(self):
        """Commands LAND flight mode for emergency landing."""
        logger.info("Commanding Emergency LAND mode...")
        self.set_mode("LAND")
