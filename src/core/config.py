from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class BaresipConfig(BaseSettings):
    host: str = Field(default="localhost", description="Baresip host")
    ctrl_tcp_port: int = Field(default=4444, description="Baresip control TCP port")
    sip_domain: str = Field(default="sip.exolve.ru", description="SIP domain from EXOLVE_SIP_DOMAIN")
    
    model_config = SettingsConfigDict(env_prefix="BARESIP_")


class AudioConfig(BaseSettings):
    in_device: str = Field(default="Baresip-RemoteAudio", description="Input audio device name")
    out_device: str = Field(default="Baresip-CallInput", description="Output audio device name")
    sample_rate_telephony: int = Field(default=8000, description="Telephony sample rate (Hz)")
    sample_rate_ai: int = Field(default=16000, description="AI sample rate (Hz)")
    chunk_size_ms: int = Field(default=20, description="Audio chunk size in milliseconds")
    
    model_config = SettingsConfigDict(env_prefix="AUDIO_")
    
    @property
    def chunk_size_telephony(self) -> int:
        return int(self.sample_rate_telephony * self.chunk_size_ms / 1000)
    
    @property
    def chunk_size_ai(self) -> int:
        return int(self.sample_rate_ai * self.chunk_size_ms / 1000)


class ElevenLabsConfig(BaseSettings):
    api_key: str = Field(description="ElevenLabs API key")
    agent_id: str = Field(description="ElevenLabs agent ID")
    ws_url: str = Field(
        default="wss://api.elevenlabs.io/v1/convai/conversation",
        description="ElevenLabs WebSocket URL"
    )
    
    model_config = SettingsConfigDict(env_prefix="ELEVENLABS_")


class ExolveConfig(BaseSettings):
    api_key: str = Field(description="Exolve API key")
    api_url: str = Field(default="https://api.exolve.ru", description="Exolve API URL")
    sip_user: str = Field(description="SIP username")
    sip_password: str = Field(description="SIP password")
    sip_domain: str = Field(default="sip.exolve.ru", description="SIP domain")
    
    model_config = SettingsConfigDict(env_prefix="EXOLVE_")


class AppConfig(BaseSettings):
    host: str = Field(default="0.0.0.0", description="Application host")
    port: int = Field(default=8000, description="Application port")
    log_level: str = Field(default="INFO", description="Logging level")
    debug: bool = Field(default=False, description="Debug mode")
    
    model_config = SettingsConfigDict(env_prefix="APP_")


class Settings(BaseSettings):
    # Direct fields from .env
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")
    debug: bool = Field(default=False)
    
    # Baresip
    baresip_host: str = Field(default="localhost")
    baresip_ctrl_tcp_port: int = Field(default=4444)
    
    # Audio
    audio_in_device: str = Field(default="Baresip-RemoteAudio")
    audio_out_device: str = Field(default="Baresip-CallInput")
    audio_sample_rate_telephony: int = Field(default=8000)
    audio_sample_rate_ai: int = Field(default=16000)
    
    # ElevenLabs
    elevenlabs_api_key: str = Field(default="")
    elevenlabs_agent_id: str = Field(default="")
    elevenlabs_ws_url: str = Field(default="wss://api.elevenlabs.io/v1/convai/conversation")
    
    # Exolve
    exolve_api_key: str = Field(default="")
    exolve_sip_user: str = Field(default="")
    exolve_sip_pass: str = Field(default="")
    exolve_sip_domain: str = Field(default="sip.exolve.ru")
    exolve_caller_id: str = Field(default="")
    exolve_static_ip_server: str = Field(default="80.75.130.99")
    exolve_sip_id_server: str = Field(default="80.75.130.100")
    exolve_sip_redirect_server: str = Field(default="80.75.130.101")
    
    # Proxy
    use_proxy: bool = Field(default=False)
    proxy_type: str = Field(default="socks5")
    proxy_host: str = Field(default="")
    proxy_port: int = Field(default=8000)
    proxy_user: str = Field(default="")
    proxy_pass: str = Field(default="")
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )


def get_settings() -> Settings:
    return Settings()