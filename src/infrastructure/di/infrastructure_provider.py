from dishka import Provider, Scope, provide

from src.core.config import Settings, BaresipConfig, AudioConfig, ElevenLabsConfig
from src.infrastructure.ai.elevenlabs_client import ElevenLabsClient
from src.infrastructure.audio.audio_bridge import AudioBridge
from src.infrastructure.telephony.baresip_controller import BaresipController


class InfrastructureProvider(Provider):
    scope = Scope.APP
    
    @provide
    def provide_baresip_controller(self, settings: Settings) -> BaresipController:
        # Создаём объект конфигурации из плоских настроек
        config = BaresipConfig(
            host=settings.baresip_host,
            ctrl_tcp_port=settings.baresip_ctrl_tcp_port,
            sip_domain=settings.exolve_sip_domain  # Берём из EXOLVE_SIP_DOMAIN
        )
        return BaresipController(config)
    
    @provide
    def provide_audio_bridge(self, settings: Settings) -> AudioBridge:
        # Создаём объект конфигурации из плоских настроек
        config = AudioConfig(
            in_device=settings.audio_in_device,
            out_device=settings.audio_out_device,
            sample_rate_telephony=settings.audio_sample_rate_telephony,
            sample_rate_ai=settings.audio_sample_rate_ai
        )
        return AudioBridge(config)
    
    @provide
    def provide_elevenlabs_client(self, settings: Settings) -> ElevenLabsClient:
        # Создаём объект конфигурации из плоских настроек
        config = ElevenLabsConfig(
            api_key=settings.elevenlabs_api_key,
            agent_id=settings.elevenlabs_agent_id,
            ws_url=settings.elevenlabs_ws_url
        )
        return ElevenLabsClient(config)