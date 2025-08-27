from dishka import Provider, Scope, provide

from src.infrastructure.ai.elevenlabs_client import ElevenLabsClient
from src.infrastructure.audio.audio_bridge import AudioBridge
from src.infrastructure.telephony.baresip_controller import BaresipController
from src.repositories.call_repository import CallRepository
from src.services.call_service import CallService


class ServiceProvider(Provider):
    scope = Scope.REQUEST
    
    @provide
    def provide_call_service(
        self,
        baresip_controller: BaresipController,
        audio_bridge: AudioBridge,
        elevenlabs_client: ElevenLabsClient,
        call_repository: CallRepository
    ) -> CallService:
        return CallService(
            baresip_controller=baresip_controller,
            audio_bridge=audio_bridge,
            elevenlabs_client=elevenlabs_client,
            call_repository=call_repository
        )