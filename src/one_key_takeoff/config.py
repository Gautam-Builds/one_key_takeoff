from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Application Settings
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000

    # WhatsApp / Webhook Settings
    whapi_token: str = ""

    # Drone Connection Settings
    drone_connection_string: str = "/dev/ttyUSB0"
    drone_baudrate: int = 115200
    drone_connection_timeout: int = 10
    drone_arm_timeout: int = 30

    # Flight & Safety Boundaries
    home_lat: float = 10.010624
    home_lon: float = 76.3133952
    max_geofence_meters: float = 2000.0
    takeoff_altitude_meters: float = 20.0
    hover_time_seconds: int = 5

    # Logging Settings
    log_level: str = "INFO"
    log_dir: str = "logs"

    # Pydantic Settings Config
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


# Global settings instance
settings = Settings()
