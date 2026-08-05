# One-Key Takeoff & Autonomous Drone Navigation API

A minimal, production-grade FastAPI service and MAVLink telemetry controller for ArduPilot multirotors and SITL (Software-In-The-Loop) drone simulators.

---

## 🚀 Quickstart & Developer Workflow

### 1. Requirements & Setup
Ensure [uv](https://github.com/astral-sh/uv) is installed:

```bash
# Clone repository
git clone <repository-url>
cd one_key_takeoff

# Install dependencies in virtual environment
uv sync
```

---

### 2. Start SITL Simulator (Terminal 1)
Run SITL directly via `uvx` with custom home coordinates (e.g. Kerala, India):

```bash
uvx dronekit-sitl copter --home=9.9816,76.2999,0,180
```

* **SITL Home Coordinates**: Latitude `9.9816° N`, Longitude `76.2999° E`, `0m` Altitude, Heading `180°`.
* **MAVLink Server Endpoint**: TCP `127.0.0.1:5760`.

---

### 3. Start One-Key Takeoff API (Terminal 2)
Run the FastAPI webhook application:

```bash
uv run one-key-takeoff
```

* **API Server**: Listening on `http://0.0.0.0:8000`.
* **Health Check**: `GET http://localhost:8000/health`.
* **Webhook Endpoint**: `POST http://localhost:8000/webhook/messages`.

---

### 4. Trigger Autonomous Mission (Terminal 3)

Send a target location pin webhook payload via `curl`:

```bash
curl -X POST http://localhost:8000/webhook/messages \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "chat_id": "+919876543210@c.us",
        "from_me": false,
        "location": {
          "latitude": 9.9825,
          "longitude": 76.2999
        }
      }
    ]
  }'
```

The API worker will automatically:
1. Validate target distance against maximum geofence (`20,000m`).
2. Arm motors in `GUIDED` mode.
3. Take off to `15.0m` relative altitude.
4. Navigate closed-loop to target GPS coordinates (`9.9825, 76.2999`).
5. Hover for 5 seconds.
6. Execute `RTL` (Return to Launch) and land safely.

---

## 🛠️ Testing

Run schema unit tests:

```bash
uv run pytest test/test_schemas.py
```

Run full closed-loop SITL mission test (with SITL running in Terminal 1):

```bash
uv run pytest test/test_sitl_mission.py
```

---

## 📂 Project Architecture

```
one_key_takeoff/
├── pyproject.toml               # Project definition & dependencies
├── README.md                    # Setup and workflow instructions
├── .env.example                 # Environment configuration template
├── src/
│   └── one_key_takeoff/
│       ├── config.py            # Pydantic environment configuration
│       ├── logger.py            # Centralized logging setup
│       ├── main.py              # FastAPI server & webhook router
│       ├── mission.py           # Closed-loop autonomous flight logic
│       ├── notifier.py          # Notification service (Whapi / Log)
│       ├── schemas.py           # Pydantic payload models
│       └── telemetry.py         # PyMAVLink DroneController driver
└── test/
    ├── test_connection.py       # MAVLink heartbeat & connection check
    ├── test_schemas.py          # Payload & distance math unit tests
    └── test_sitl_mission.py     # Closed-loop SITL mission verification
```
