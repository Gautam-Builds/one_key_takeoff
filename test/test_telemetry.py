from unittest.mock import MagicMock

from pymavlink.dialects.v20 import ardupilotmega as mavlink

from one_key_takeoff.telemetry import DroneController


def test_check_prearm_messages_string(caplog):
    controller = DroneController.__new__(DroneController)

    msg_str = MagicMock()
    msg_str.text = "PreArm: High GPS HDOP"

    controller.master = MagicMock()
    controller.master.recv_match.side_effect = [msg_str, None]

    with caplog.at_level("WARNING"):
        controller.check_prearm_messages()

    assert "🚁 ArduPilot: PreArm: High GPS HDOP" in caplog.text


def test_check_prearm_messages_bytes(caplog):
    controller = DroneController.__new__(DroneController)

    msg_bytes = MagicMock()
    msg_bytes.text = b"PreArm: EKF check failure"

    controller.master = MagicMock()
    controller.master.recv_match.side_effect = [msg_bytes, None]

    with caplog.at_level("WARNING"):
        controller.check_prearm_messages()

    assert "🚁 ArduPilot: PreArm: EKF check failure" in caplog.text


def test_check_prearm_messages_no_master(caplog):
    controller = DroneController.__new__(DroneController)
    controller.master = None

    with caplog.at_level("WARNING"):
        controller.check_prearm_messages()

    assert "Checking ArduPilot status messages..." not in caplog.text


def test_arm_and_takeoff_prearm_failure_raises():
    controller = DroneController.__new__(DroneController)
    controller.master = MagicMock()
    controller.verify_prearm_checks = MagicMock(return_value=False)

    import pytest

    with pytest.raises(RuntimeError, match="Pre-arm checks failed"):
        controller.arm_and_takeoff(20.0)


def test_set_parameter_byte_padding_and_ack():
    controller = DroneController.__new__(DroneController)
    controller.master = MagicMock()
    controller._is_closing = False
    controller.master.target_system = 1
    controller.master.target_component = 1

    param_ack = MagicMock()
    param_ack.param_id = "CIRCLE_RADIUS"
    param_ack.param_value = 1000.0
    controller.master.recv_match.return_value = param_ack

    result = controller.set_parameter("CIRCLE_RADIUS", 1000.0)

    assert result is True
    # Verify parameter_id was null-padded to 16 bytes
    args = controller.master.mav.param_set_send.call_args[0]
    param_bytes = args[2]
    assert len(param_bytes) == 16
    assert param_bytes == b"CIRCLE_RADIUS\x00\x00\x00"
    assert args[4] == mavlink.MAV_PARAM_TYPE_REAL32


def test_heartbeat_thread_start_and_stop():
    controller = DroneController.__new__(DroneController)
    controller.master = MagicMock()
    controller._is_closing = False
    import threading

    controller._stop_heartbeat = threading.Event()
    controller._heartbeat_thread = None

    controller._start_heartbeat_thread()
    assert controller._heartbeat_thread is not None
    assert controller._heartbeat_thread.is_alive()

    controller.close()
    assert controller._is_closing is True
    assert controller.master is None
