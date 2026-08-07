from unittest.mock import MagicMock

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
