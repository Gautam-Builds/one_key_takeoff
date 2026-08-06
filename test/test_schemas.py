from geopy.distance import geodesic

from one_key_takeoff.schemas import WebhookPayload


def test_webhook_location_payload_parsing():
    raw_data = {
        "messages": [
            {
                "chat_id": "+1234567890",
                "from_me": False,
                "location": {"latitude": 9.9816, "longitude": 76.2999},
            }
        ]
    }
    payload = WebhookPayload.model_validate(raw_data)
    assert len(payload.messages) == 1
    msg = payload.messages[0]
    assert msg.chat_id == "+1234567890"
    assert msg.from_me is False
    assert msg.location is not None
    assert msg.location.latitude == 9.9816
    assert msg.location.longitude == 76.2999


def test_geodesic_distance_calculation():
    home = (9.9816, 76.2999)
    target = (9.9826, 76.3009)
    dist = geodesic(home, target).meters
    assert dist > 0.0
    assert dist < 500.0
