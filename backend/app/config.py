from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_env: str = "local"
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    spotify_client_id: str = ""
    spotify_client_secret: str = ""
    spotify_redirect_uri: str = "http://localhost:8000/auth/spotify/callback"
    anthropic_api_key: str = ""
    groq_api_key: str = ""
    youtube_api_key: str = ""
    jwt_secret: str = "dev_change_me"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
