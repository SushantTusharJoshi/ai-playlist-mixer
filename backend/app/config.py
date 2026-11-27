from pydantic import ConfigDict
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = ConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://localhost:8000/auth/spotify/callback"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    youtube_api_key: str = ""
    max_parties: int = 500
    max_queue: int = 200
    youtube_calls_per_minute: int = 30

settings = Settings()
