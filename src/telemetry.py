import time
from pymavlink import mavutil
from .logger import logger

class DroneController:
    def __init__(self, connection_string: str):
        logger.info(f"Connecting to drone at {connection_string}...")
        # Start MAVLink connection
        self.master = mavutil.mavlink_connection(connection_string)
        self.master.wait_heartbeat()
        logger.info("Heartbeat received! Drone connected.")

    def set_mode(self, mode: str):
        # ArduPilot specific mode mapping
        mode_id = self.master.mode_mapping()[mode]
        self.master.mav.set_mode_send(
            self.master.target_system,
            mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
            mode_id
        )
        logger.info(f"Flight mode set to {mode}")

    # def arm_and_takeoff(self, altitude: float):
    #     self.set_mode("GUIDED")
    #     time.sleep(1)
        
    #     logger.info("Arming motors...")
    #     self.master.mav.command_long_send(
    #         self.master.target_system, self.master.target_component,
    #         mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
    #         0, 1, 0, 0, 0, 0, 0, 0
    #     )
    #     self.master.motors_armed_wait()
    #     logger.info("Motors armed!")

    #     logger.info(f"Taking off to {altitude} meters...")
    #     self.master.mav.command_long_send(
    #         self.master.target_system, self.master.target_component,
    #         mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
    #         0, 0, 0, 0, 0, 0, 0, altitude
    #     )

    def arm_and_takeoff(self, altitude: float):
        self.set_mode("GUIDED")
        time.sleep(1)
        
        logger.info("Requesting arm (waiting for GPS/EKF lock to clear)...")
        
        # Keep trying to arm until successful
        while not self.master.motors_armed():
            # Send the arm command
            self.master.mav.command_long_send(
                self.master.target_system, self.master.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                0, 1, 0, 0, 0, 0, 0, 0
            )
            
            # Listen for ArduPilot's text responses to see why it's rejecting us
            msg = self.master.recv_match(type='STATUSTEXT', blocking=False)
            if msg:
                logger.info(f"Drone Status: {msg.text}")
                
            # Wait 3 seconds before trying again to avoid spamming the flight controller
            time.sleep(3)
            
        logger.info("Motors successfully armed!")

        logger.info(f"Taking off to {altitude} meters...")
        self.master.mav.command_long_send(
            self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
            0, 0, 0, 0, 0, 0, 0, altitude
        )

    def fly_to(self, lat: float, lon: float, alt: float):
        logger.info(f"Navigating to {lat}, {lon} at {alt}m...")
        # Command drone to a specific global coordinate
        self.master.mav.set_position_target_global_int_send(
            0, self.master.target_system, self.master.target_component,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
            0b0000111111111000, # Mask to enable position control only
            int(lat * 1e7), int(lon * 1e7), alt,
            0, 0, 0, 0, 0, 0, 0, 0
        )
        
    def rtl(self):
        logger.info("Returning to Launch (RTL)...")
        self.set_mode("RTL")