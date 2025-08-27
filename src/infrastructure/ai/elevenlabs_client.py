import asyncio
import base64
import json
from typing import Optional, Callable, Any, Protocol, Union
from dataclasses import dataclass
from enum import Enum

import websockets
import websockets.client
from websockets_proxy import Proxy, proxy_connect
import numpy as np
import g711
import structlog

from src.infrastructure.audio.audio_types import AudioFrame


class ElevenLabsConfig(Protocol):
    """Protocol для конфигурации ElevenLabs"""
    api_key: str
    agent_id: str
    ws_url: str


logger = structlog.get_logger()


class EventType(str, Enum):
    CONVERSATION_INITIATION = "conversation_initiation_metadata"
    USER_TRANSCRIPT = "user_transcript"
    AGENT_RESPONSE = "agent_response"
    AUDIO = "audio"
    INPUT_AUDIO_BUFFER_APPEND = "input_audio_buffer.append"
    INPUT_AUDIO_BUFFER_COMMIT = "input_audio_buffer.commit"
    INPUT_AUDIO_BUFFER_CLEAR = "input_audio_buffer.clear"
    INTERRUPTION = "interruption"
    PING = "ping"
    PONG = "pong"


@dataclass
class ElevenLabsEvent:
    type: EventType
    data: dict[str, Any]


class ElevenLabsClient:
    def __init__(self, config: ElevenLabsConfig, proxy_config: Optional[dict] = None) -> None:
        self.config = config
        self.proxy_config = proxy_config
        self.websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        
        self.audio_format: str = "pcm_16000"
        self.output_format: str = "ulaw_8000"
        
        self._on_audio_callback: Optional[Callable[[AudioFrame], None]] = None
        self._on_transcript_callback: Optional[Callable[[str, bool], None]] = None
        
        self._audio_buffer: list[bytes] = []
        self._buffer_duration_ms = 100
        
        # Ping-pong для поддержания соединения
        self._ping_task: Optional[asyncio.Task] = None
        self._ping_interval = 20  # секунд
        
    def _cfg(self, key: str, default: Optional[Any] = None) -> Any:
        """Helper to read values from config whether it's an object or dict."""
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        # Fallback for Settings with different field names
        if not hasattr(self.config, key):
            # allow ELEVENLABS_* style from Settings
            if key == "ws_url" and hasattr(self.config, "elevenlabs_ws_url"):
                return getattr(self.config, "elevenlabs_ws_url")
        return getattr(self.config, key, default)

    async def connect(self) -> None:
        if self._running:
            logger.warning("ElevenLabs WebSocket already connected, skipping")
            return
        
        logger.info("🔌 CONNECTING TO ELEVENLABS WEBSOCKET API")
        logger.info(f"Agent ID: {self._cfg('agent_id')}")
        print(f"[ElevenLabs] 🔌 Connecting to WebSocket...")
        
        try:
            url_base = self._cfg("ws_url", "wss://api.elevenlabs.io/v1/convai/conversation")
            url = f"{url_base}?agent_id={self._cfg('agent_id')}"
            headers = {
                "xi-api-key": self._cfg('api_key'),
            }
            
            # Подключение с или без прокси
            if self.proxy_config and self.proxy_config.get('use_proxy'):
                # Создаём прокси объект
                proxy_url = (
                    f"{self.proxy_config['proxy_type']}://"
                    f"{self.proxy_config['proxy_user']}:{self.proxy_config['proxy_pass']}@"
                    f"{self.proxy_config['proxy_host']}:{self.proxy_config['proxy_port']}"
                )
                
                logger.info(
                    "🌐 Connecting to ElevenLabs via proxy",
                    proxy_type=self.proxy_config['proxy_type'],
                    proxy_host=self.proxy_config['proxy_host'],
                    proxy_port=self.proxy_config['proxy_port']
                )
                
                proxy = Proxy.from_url(proxy_url)
                
                # Подключаемся через прокси
                self.websocket = await proxy_connect(
                    url,
                    proxy=proxy,
                    extra_headers=headers
                )
                
                logger.info("✅ Connected to ElevenLabs through proxy successfully!")
            else:
                # Прямое подключение без прокси
                logger.info("Connecting to ElevenLabs directly (without proxy)")
                logger.warning("⚠️  Direct connection may fail if ElevenLabs is blocked in your region!")
                
                # Для новой версии websockets используем additional_headers
                try:
                    self.websocket = await websockets.connect(
                        url,
                        additional_headers=headers
                    )
                except TypeError:
                    # Fallback для старых версий
                    self.websocket = await websockets.client.connect(
                        url,
                        extra_headers=headers
                    )
            
            self._running = True
            print(f"[ElevenLabs] ✅ WebSocket connected")
            
            # Ожидаем начальное событие
            print(f"[ElevenLabs] ⏳ Waiting for init event...")
            init_event = await self._receive_event()
            print(f"[ElevenLabs] 📥 Received event: {init_event.type if init_event else 'None'}")
            if init_event and init_event.type == EventType.CONVERSATION_INITIATION:
                # Данные находятся прямо в корне события
                self.audio_format = init_event.data.get("user_input_audio_format", "pcm_16000")
                self.output_format = init_event.data.get("agent_output_audio_format", "pcm_16000")
                
                logger.info(
                    "Received conversation initiation",
                    audio_format=self.audio_format,
                    output_format=self.output_format
                )
                print(f"[ElevenLabs] 🎬 Conversation initialized, audio format: {self.output_format}")
                
                # КРИТИЧНО: Отправляем conversation_initiation_metadata обратно!
                await self.websocket.send(json.dumps({
                    "type": "conversation_initiation_metadata",
                    "conversation_initiation_metadata_event": {
                        "conversation_id": init_event.data.get("conversation_id", ""),
                        "agent_output_audio_format": self.output_format
                    }
                }))
                logger.info("Sent conversation_initiation_metadata response")
                print(f"[ElevenLabs] ✅ Handshake completed")
            else:
                logger.warning(f"Unexpected init event: {init_event}")
            
            # Запускаем ping задачу ПОСЛЕ handshake
            self._ping_task = asyncio.create_task(self._ping_loop())
            
        except Exception as e:
            logger.error("Failed to connect to ElevenLabs", error=str(e))
            print(f"[ElevenLabs] ❌ Connection failed: {e}")
            raise
    
    async def disconnect(self) -> None:
        if not self._running:
            return
        
        self._running = False
        
        # Останавливаем ping задачу
        if self._ping_task:
            self._ping_task.cancel()
            try:
                await self._ping_task
            except asyncio.CancelledError:
                pass
            self._ping_task = None
        
        if self.websocket:
            await self.websocket.close()
            self.websocket = None
        
        logger.info("Disconnected from ElevenLabs")
    
    async def _receive_event(self) -> Optional[ElevenLabsEvent]:
        if not self.websocket:
            return None
        
        try:
            message = await self.websocket.recv()
            if isinstance(message, (bytes, bytearray)):
                # Expect JSON text messages; if bytes, decode first
                message = message.decode("utf-8", errors="ignore")
            data = json.loads(message)
            
            # Обрабатываем структуру ElevenLabs событий
            event_type = data.get("type")
            
            # Если type не найден в корне, ищем в подобъектах
            if not event_type:
                # Проверяем альтернативные форматы событий
                if "audio_event" in data:
                    event_type = "audio"
                    # Извлекаем аудио данные из вложенного объекта
                    if "audio_base_64" in data["audio_event"]:
                        data["audio"] = data["audio_event"]["audio_base_64"]
                elif "agent_response_event" in data:
                    event_type = "agent_response" 
                    # Извлекаем аудио из agent_response_event
                    if "audio_base_64" in data["agent_response_event"]:
                        data["audio"] = data["agent_response_event"]["audio_base_64"]
                elif "ping_event" in data:
                    event_type = "ping"
                elif "conversation_initiation_metadata_event" in data:
                    event_type = "conversation_initiation_metadata"
                    # Перемещаем данные на верхний уровень
                    data.update(data["conversation_initiation_metadata_event"])
                else:
                    logger.debug(f"Unknown event structure: {list(data.keys())}")
                    return None
            
            # Обрабатываем известные типы событий
            try:
                event_type_enum = EventType(event_type)
            except ValueError:
                # Неизвестный тип события - логируем и пропускаем
                logger.debug(f"Unknown event type: {event_type}")
                return None
            
            return ElevenLabsEvent(
                type=event_type_enum,
                data=data
            )
        except json.JSONDecodeError as e:
            logger.error("Failed to decode message", error=str(e))
            return None
        except Exception as e:
            logger.error("Failed to receive message", error=str(e))
            return None
    
    async def send_audio(self, audio_bytes: bytes) -> None:
        """Отправляет аудио данные в WebSocket"""
        if not self.websocket or not self._running:
            return
        
        try:
            self._audio_buffer.append(audio_bytes)
            
            buffer_size = sum(len(chunk) for chunk in self._audio_buffer)
            # Для 16kHz, 16-bit (2 bytes per sample)
            expected_size = int(16000 * self._buffer_duration_ms / 1000 * 2)
            
            if buffer_size >= expected_size:
                combined_audio = b''.join(self._audio_buffer)
                self._audio_buffer.clear()
                
                audio_base64 = base64.b64encode(combined_audio).decode('ascii')
                
                await self.websocket.send(json.dumps({
                    "type": EventType.INPUT_AUDIO_BUFFER_APPEND.value,
                    "audio": audio_base64
                }))
                
                await self.websocket.send(json.dumps({
                    "type": EventType.INPUT_AUDIO_BUFFER_COMMIT.value
                }))
        except websockets.exceptions.ConnectionClosed:
            logger.error("WebSocket connection closed while sending audio")
            self._running = False
        except Exception as e:
            logger.error(f"Error sending audio: {e}")
    
    async def receive_audio(self) -> Optional[bytes]:
        """Получает аудио данные из WebSocket"""
        if not self._running or not self.websocket:
            return None
        
        try:
            event = await self._receive_event()
            if event:
                # Обрабатываем pong ответы
                if event.type == EventType.PONG:
                    logger.debug("Received pong")
                    return None
                # Обрабатываем аудио от агента
                elif event.type == EventType.AUDIO or event.type == EventType.AGENT_RESPONSE:
                    # AGENT_RESPONSE содержит и audio и текст
                    audio_base64 = event.data.get("audio")
                    if not audio_base64:
                        # Проверяем вложенные структуры (audio_event, audio_base_64)
                        if "audio_event" in event.data:
                            audio_base64 = event.data["audio_event"].get("audio_base_64")
                        elif "audio_base_64" in event.data:
                            audio_base64 = event.data.get("audio_base_64")
                        elif "agent_response_event" in event.data:
                            audio_base64 = event.data["agent_response_event"].get("audio_base_64")
                    
                    if audio_base64:
                        decoded = base64.b64decode(audio_base64)
                        logger.debug(f"Decoded audio chunk: {len(decoded)} bytes")
                        return decoded
                # Игнорируем другие события (USER_TRANSCRIPT и т.д.)
                elif event.type in [EventType.USER_TRANSCRIPT, EventType.INTERRUPTION]:
                    logger.debug(f"Ignoring event: {event.type}")
                    return None
        except websockets.exceptions.ConnectionClosed as e:
            # Проверяем причину закрытия
            if e.code == 1000:
                # Нормальное закрытие - возможно, сервер закрыл соединение
                if self._running:
                    logger.warning(f"ElevenLabs closed connection normally (code 1000): {e.reason or 'no reason'}")
                    self._running = False
            elif "Max call duration exceeded" in str(e):
                # Логируем только один раз
                if self._running:
                    logger.warning("ElevenLabs closed connection: Max call duration exceeded")
                    self._running = False
            elif self._running:
                logger.error(f"WebSocket connection closed: code={e.code}, reason={e.reason}")
                self._running = False
            return None
        except Exception as e:
            # Проверяем на лимит длительности
            if "1000" in str(e) and "Max call duration" in str(e):
                if self._running:
                    logger.warning("ElevenLabs max call duration reached")
                    self._running = False
                return None
            # Логируем ошибку только если соединение ещё активно
            if self._running:
                logger.error(f"Error receiving audio: {e}")
            return None
        
        return None
    
    async def clear_audio_buffer(self) -> None:
        if not self.websocket:
            return
        
        self._audio_buffer.clear()
        
        await self.websocket.send(json.dumps({
            "type": EventType.INPUT_AUDIO_BUFFER_CLEAR.value
        }))
    
    async def interrupt(self) -> None:
        if not self.websocket:
            return
        
        await self.websocket.send(json.dumps({
            "type": EventType.INTERRUPTION.value
        }))
        
        await self.clear_audio_buffer()
    
    async def _ping_loop(self) -> None:
        """Периодически отправляет ping для поддержания соединения"""
        while self._running:
            try:
                await asyncio.sleep(self._ping_interval)
                
                if self.websocket and not self.websocket.closed:
                    await self.websocket.send(json.dumps({
                        "type": EventType.PING.value
                    }))
                    logger.debug("Sent ping to keep connection alive")
                    
            except Exception as e:
                logger.error(f"Error in ping loop: {e}")
                # Не прерываем цикл при ошибке
                continue
    
    async def process_events(self) -> None:
        while self._running:
            event = await self._receive_event()
            if not event:
                continue
            
            try:
                if event.type == EventType.AUDIO_CHUNK:
                    await self._handle_audio_chunk(event.data)
                elif event.type == EventType.USER_TRANSCRIPT:
                    await self._handle_transcript(event.data, is_user=True)
                elif event.type == EventType.AGENT_RESPONSE:
                    await self._handle_transcript(event.data, is_user=False)
                elif event.type == EventType.PING:
                    await self._handle_ping()
            except Exception as e:
                logger.error(
                    "Error processing event",
                    event_type=event.type,
                    error=str(e)
                )
    
    async def _handle_audio_chunk(self, data: dict[str, Any]) -> None:
        audio_base64 = data.get("audio")
        if not audio_base64:
            return
        
        audio_bytes = base64.b64decode(audio_base64)
        
        if self.output_format == "ulaw_8000":
            ulaw_data = np.frombuffer(audio_bytes, dtype=np.uint8)
            pcm_data = g711.decode_ulaw(ulaw_data)
        elif self.output_format == "pcm_8000":
            pcm_data = np.frombuffer(audio_bytes, dtype=np.int16)
        elif self.output_format == "pcm_16000":
            pcm_data = np.frombuffer(audio_bytes, dtype=np.int16)
        else:
            logger.warning(f"Unsupported output format: {self.output_format}")
            return
        
        sample_rate = 8000 if "8000" in self.output_format else 16000
        
        frame = AudioFrame(
            data=pcm_data,
            sample_rate=sample_rate,
            timestamp=asyncio.get_event_loop().time()
        )
        
        if self._on_audio_callback:
            self._on_audio_callback(frame)
    
    async def _handle_transcript(self, data: dict[str, Any], is_user: bool) -> None:
        text = data.get("transcript") if is_user else data.get("text")
        if text and self._on_transcript_callback:
            self._on_transcript_callback(text, is_user)
    
    async def _handle_ping(self) -> None:
        if self.websocket:
            await self.websocket.send(json.dumps({
                "type": EventType.PONG
            }))
    
    def set_audio_callback(self, callback: Callable[[AudioFrame], None]) -> None:
        self._on_audio_callback = callback
    
    def set_transcript_callback(self, callback: Callable[[str, bool], None]) -> None:
        self._on_transcript_callback = callback
    
    async def __aenter__(self) -> "ElevenLabsClient":
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()
