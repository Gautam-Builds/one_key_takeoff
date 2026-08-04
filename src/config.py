from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    whatsapp_verify_token: str = ""
    whatsapp_api_key: str = ""

    # This tells Pydantic to read from our .env file
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

# Create a global settings instance to import throughout the app
settings = Settings()