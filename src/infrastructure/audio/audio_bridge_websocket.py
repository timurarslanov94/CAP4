"""
Аудио мост между Baresip и ElevenLabs WebSocket через разные транспорты.
"""

import asyncio
from typing import Optional
from dataclasses import dataclass

import structlog

from src.infrastructure.audio.audio_transport import (
    AudioTransport, 
    NamedPipeTransport,
    AudioConfig,
    AudioFormat,
    AudioResampler
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.core.config import AudioConfig as AppAudioConfig, ElevenLabsConfig


logger = structlog.get_logger()


@dataclass
class BridgeMetrics:
    """Метрики работы моста"""
    packets_from_caller: int = 0
    packets_to_caller: int = 0
    packets_from_ai: int = 0
    packets_to_ai: int = 0
    bytes_from_caller: int = 0
    bytes_to_caller: int = 0
    bytes_from_ai: int = 0
    bytes_to_ai: int = 0
    resampling_operations: int = 0
    errors: int = 0


class AudioBridgeWebSocket:
    """
    Мост между телефонным звонком (Baresip) и AI (ElevenLabs).
    
    Архитектура:
    [Caller] <--> [Baresip] <--> [Pipes] <--> [AudioBridge] <--> [WebSocket] <--> [ElevenLabs]
    
    Поток данных:
    1. Caller говорит → Baresip → pipe_out → resample 8k→16k → WebSocket → ElevenLabs
    2. ElevenLabs отвечает → WebSocket → resample 16k→8k → pipe_in → Baresip → Caller
    """
    
    def __init__(self, 
                 audio_config: "AppAudioConfig",
                 elevenlabs_config: "ElevenLabsConfig",
                 transport: Optional[AudioTransport] = None,
                 proxy_config: Optional[dict] = None):
        
        # Конфигурация форматов
        self.telephony_format = AudioFormat.PCM_16BIT_8KHZ_MONO  # Baresip
        self.ai_format = AudioFormat.PCM_16BIT_16KHZ_MONO  # ElevenLabs
        
        # Создаём транспорты
        if transport:
            self.transport = transport
        else:
            # По умолчанию используем named pipes
            telephony_config = AudioConfig(
                format=self.telephony_format,
                chunk_duration_ms=audio_config.chunk_size_ms
            )
            self.transport = NamedPipeTransport(telephony_config)
        
        # ElevenLabs клиент (импортируем здесь чтобы избежать циклических импортов)
        from src.infrastructure.ai.elevenlabs_client import ElevenLabsClient
        self.elevenlabs = ElevenLabsClient(elevenlabs_config, proxy_config)
        
        # Ресэмплер
        self.resampler = AudioResampler()
        
        # Состояние
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self.metrics = BridgeMetrics()
        
        # Очереди для буферизации
        self._to_ai_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._from_ai_queue: asyncio.Queue = asyncio.Queue(maxsize=50)

    def _normalize_ai_audio_to_pcm16k(self, audio_bytes: bytes) -> bytes:
        """Ensure AI audio is PCM 16kHz 16-bit for downstream processing.
        ElevenLabs may return 'ulaw_8000' or 'pcm_8000' depending on agent settings.
        """
        fmt = getattr(self.elevenlabs, "output_format", "pcm_16000") or "pcm_16000"
        try:
            if fmt == "ulaw_8000":
                import g711
                # Decode μ-law (uint8) -> PCM16 at 8kHz
                ulaw = bytes(audio_bytes)
                pcm8 = g711.decode_ulaw(ulaw)
                # g711 may return numpy array or bytes; ensure bytes
                if hasattr(pcm8, "tobytes"):
                    pcm8 = pcm8.tobytes()
                # Upsample to 16kHz
                return self.resampler.resample_pcm(pcm8, from_rate=8000, to_rate=16000)
            elif fmt == "pcm_8000":
                # Direct upsample to 16kHz
                return self.resampler.resample_pcm(audio_bytes, from_rate=8000, to_rate=16000)
            # Default: already pcm_16000
            return audio_bytes
        except Exception:
            # Fallback: return as-is to avoid breaking flow
            return audio_bytes
    
    async def start_transport_only(self) -> None:
        """Запуск только транспорта (pipes) без WebSocket"""
        if self._running:
            return
        
        logger.info("Starting audio transport (pipes only)...")
        print("[Bridge] 🚀 Transport-only start: opening pipes and reader task")
        
        # Запускаем только транспорт
        await self.transport.start()
        
        # ВАЖНО: Устанавливаем флаг запуска для транспорта
        self._running = True
        
        # Запускаем задачу чтения из pipes (она будет накапливать в очереди)
        # Но НЕ запускаем отправку в ElevenLabs!
        self._tasks = [
            asyncio.create_task(self._process_caller_to_ai(), name="caller_to_ai")
        ]
        logger.info("Started audio reader task, buffering audio from pipes")
        print("[Bridge] 📡 Reader task started; waiting for SIP 200 connect signal")
        
        # НЕ подключаемся к ElevenLabs!
        # Это будет сделано позже при реальном ответе (SIP 200 OK)
        
        logger.info("Audio transport ready, waiting for real answer to connect WebSocket")
    
    async def start_websocket(self) -> None:
        """Запуск WebSocket к ElevenLabs (вызывается при SIP 200 OK)"""
        if self.elevenlabs._running:
            logger.warning("WebSocket already connected, skipping")
            return
            
        logger.info("🔌 CONNECTING TO ELEVENLABS WEBSOCKET (SIP 200 OK received)")
        print("[Bridge] 🔌 CONNECTING TO ELEVENLABS WEBSOCKET")
        logger.info("Starting ElevenLabs WebSocket connection...")
        logger.info(f"   Transport type: {type(self.transport).__name__}")
        logger.info(f"   Transport running: {hasattr(self.transport, '_running') and self.transport._running}")
        
        # Подключаемся к ElevenLabs
        logger.info("Connecting to ElevenLabs API...")
        await self.elevenlabs.connect()
        logger.info("ElevenLabs API connected successfully")
        print("[Bridge] ✅ ElevenLabs WebSocket connected")
        
        # Добавляем остальные задачи обработки (caller_to_ai уже запущен)
        logger.info("Starting remaining audio processing tasks...")
        additional_tasks = [
            asyncio.create_task(self._process_ai_to_caller(), name="ai_to_caller"),
            asyncio.create_task(self._send_to_ai(), name="send_to_ai"),
            asyncio.create_task(self._receive_from_ai(), name="receive_from_ai"),
            asyncio.create_task(self._monitor_metrics(), name="monitor_metrics")
        ]
        self._tasks.extend(additional_tasks)
        logger.info(f"Started {len(additional_tasks)} additional tasks, total: {len(self._tasks)}")
        
        logger.info("WebSocket connected and audio bridge fully started")
        print("[Bridge] ✅ Audio bridge fully started (WS + queues)")
    
    async def start(self) -> None:
        """Старый метод для совместимости - НЕ ИСПОЛЬЗОВАТЬ!"""
        logger.error("❌ DEPRECATED: start() called - use start_transport_only() + start_websocket() separately!")
        await self.start_transport_only()
        # НЕ запускаем WebSocket автоматически!
        # await self.start_websocket()
    
    async def stop(self) -> None:
        """Остановка моста"""
        if not self._running:
            return
        
        logger.info("Stopping audio bridge...")
        self._running = False
        
        # Отменяем задачи
        for task in self._tasks:
            task.cancel()
        
        # Ждём завершения
        await asyncio.gather(*self._tasks, return_exceptions=True)
        
        # Останавливаем компоненты
        await self.elevenlabs.disconnect()
        await self.transport.stop()
        
        logger.info(
            "Audio bridge stopped",
            metrics={
                "packets_processed": self.metrics.packets_from_caller + self.metrics.packets_from_ai,
                "bytes_transferred": self.metrics.bytes_from_caller + self.metrics.bytes_from_ai,
                "errors": self.metrics.errors
            }
        )
    
    async def _process_caller_to_ai(self) -> None:
        """Обработка аудио от звонящего к AI"""
        logger.info("🎤 Started caller_to_ai task - reading from pipes")
        logger.info(f"   Transport: {type(self.transport).__name__}")
        logger.info(f"   Transport running: {hasattr(self.transport, '_running') and self.transport._running}")
        chunks_read = 0
        empty_reads = 0
        
        while self._running:
            try:
                # Читаем чанк от Baresip (8kHz)
                chunk = await self.transport.read_chunk()
                if not chunk:
                    empty_reads += 1
                    if empty_reads % 1000 == 0:  # Логируем каждую 1000-ю пустую попытку
                        logger.info(f"⚠️ No audio from pipe: {empty_reads} empty reads")
                    await asyncio.sleep(0.001)
                    continue
                
                chunks_read += 1
                if chunks_read == 1:
                    logger.info(f"🎉 FIRST AUDIO CHUNK RECEIVED! Size={len(chunk)} bytes")
                    print(f"[Bridge] 🎉 First caller audio chunk: {len(chunk)} bytes")
                elif chunks_read % 50 == 0:  # Логируем каждый 50-й чанк
                    logger.info(f"📊 Audio flowing: chunk #{chunks_read}, size={len(chunk)} bytes")
                
                self.metrics.packets_from_caller += 1
                self.metrics.bytes_from_caller += len(chunk)
                
                # Ресэмплинг 8kHz → 16kHz
                resampled = self.resampler.resample_pcm(
                    chunk, 
                    from_rate=8000, 
                    to_rate=16000
                )
                self.metrics.resampling_operations += 1
                
                # Кладём в очередь для отправки
                await self._to_ai_queue.put(resampled)
                
            except Exception as e:
                self.metrics.errors += 1
                logger.error("Error processing caller audio", error=str(e))
                await asyncio.sleep(0.01)
    
    async def _process_ai_to_caller(self) -> None:
        """Обработка аудио от AI к звонящему"""
        logger.info("🔊 Started ai_to_caller task - writing to pipes")
        print("[Bridge] 🔊 AI-to-caller task started")
        audio_buffer = bytearray()  # Буфер для накопления аудио
        chunk_size_16k = 640  # 20ms при 16kHz (16000 * 0.02 * 2 bytes)
        chunks_written = 0
        
        while self._running:
            try:
                # Получаем из очереди от AI
                chunk = await asyncio.wait_for(
                    self._from_ai_queue.get(),
                    timeout=0.1
                )
                
                self.metrics.packets_from_ai += 1
                self.metrics.bytes_from_ai += len(chunk)
                
                # Добавляем в буфер
                audio_buffer.extend(chunk)
                
                # Логируем первый чанк от AI
                if self.metrics.packets_from_ai == 1:
                    logger.info(f"🎉 FIRST AI AUDIO IN QUEUE! Size={len(chunk)} bytes")
                    print(f"[Bridge] 🎤 First AI audio received: {len(chunk)} bytes, buffered: {len(audio_buffer)} bytes")
                elif self.metrics.packets_from_ai % 10 == 0:
                    logger.info(f"📊 Processing AI audio: packet #{self.metrics.packets_from_ai}")
                
                # Отправляем по частям размером 20ms
                while len(audio_buffer) >= chunk_size_16k:
                    # Берём ровно 20ms аудио
                    chunk_to_send = bytes(audio_buffer[:chunk_size_16k])
                    audio_buffer = audio_buffer[chunk_size_16k:]
                    
                    # Ресэмплинг 16kHz → 8kHz
                    resampled = self.resampler.resample_pcm(
                        chunk_to_send,
                        from_rate=16000,
                        to_rate=8000
                    )
                    self.metrics.resampling_operations += 1
                    
                    # Отправляем в Baresip (должно быть ровно 320 байт)
                    await self.transport.write_chunk(resampled)
                    
                    chunks_written += 1
                    if chunks_written == 1:
                        logger.info(f"🎉 FIRST CHUNK WRITTEN TO PIPE! Size={len(resampled)} bytes")
                        print(f"[Bridge] ✅ First chunk written to Baresip pipe: {len(resampled)} bytes")
                    elif chunks_written % 50 == 0:
                        logger.info(f"📊 Written {chunks_written} chunks to pipe")
                    
                    self.metrics.packets_to_caller += 1
                    self.metrics.bytes_to_caller += len(resampled)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.metrics.errors += 1
                logger.error("Error processing AI audio", error=str(e))
                await asyncio.sleep(0.01)
    
    async def _send_to_ai(self) -> None:
        """Отправка аудио в ElevenLabs WebSocket"""
        while self._running:
            try:
                # Получаем из очереди
                chunk = await asyncio.wait_for(
                    self._to_ai_queue.get(),
                    timeout=0.1
                )
                
                # Отправляем в WebSocket
                await self.elevenlabs.send_audio(chunk)
                
                self.metrics.packets_to_ai += 1
                self.metrics.bytes_to_ai += len(chunk)
                
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                self.metrics.errors += 1
                logger.error("Error sending to AI", error=str(e))
                await asyncio.sleep(0.01)
    
    async def _receive_from_ai(self) -> None:
        """Получение аудио из ElevenLabs WebSocket"""
        logger.info("📥 Started receive_from_ai task")
        print("[Bridge] 📥 Receiver from AI started")
        chunks_received = 0
        empty_receives = 0
        
        while self._running:
            try:
                # Получаем аудио от ElevenLabs
                chunk = await self.elevenlabs.receive_audio()
                if chunk:
                    # Нормализуем к PCM 16kHz, 16-bit
                    chunk = self._normalize_ai_audio_to_pcm16k(chunk)
                    chunks_received += 1
                    if chunks_received == 1:
                        logger.info(f"🎉 FIRST RESPONSE FROM ELEVENLABS! Size={len(chunk)} bytes")
                        print(f"[Bridge] 🗣️ First AI audio chunk: {len(chunk)} bytes (16k pcm normalized)")
                    elif chunks_received % 50 == 0:
                        logger.info(f"📥 From ElevenLabs: chunk #{chunks_received}")
                    
                    # Добавляем в очередь для обработки
                    await self._from_ai_queue.put(chunk)
                    if chunks_received == 1:
                        logger.info(f"✅ Added first chunk to queue, queue size: {self._from_ai_queue.qsize()}")
                        print(f"[Bridge] 📦 Queue size after adding first chunk: {self._from_ai_queue.qsize()}")
                else:
                    empty_receives += 1
                    if empty_receives % 100 == 0:
                        logger.debug(f"No audio from ElevenLabs: {empty_receives} empty receives")
                    # Проверяем, не закрылось ли соединение
                    if not self.elevenlabs._running:
                        logger.warning("ElevenLabs connection closed, stopping audio bridge")
                        self._running = False
                        break
                    # Не нужно спать если мы активно не получаем аудио
                    await asyncio.sleep(0.001)
                    
            except Exception as e:
                self.metrics.errors += 1
                # Проверяем на ошибку превышения лимита
                if "Max call duration exceeded" in str(e):
                    logger.warning("Max call duration exceeded, stopping audio bridge")
                    self._running = False
                    break
                logger.error("Error receiving from AI", error=str(e))
                await asyncio.sleep(0.01)
    
    async def _monitor_metrics(self) -> None:
        """Мониторинг метрик для отладки"""
        while self._running:
            await asyncio.sleep(10)  # Логируем каждые 10 секунд
            
            logger.info(
                "Audio bridge metrics",
                caller_to_ai={
                    "packets": self.metrics.packets_from_caller,
                    "bytes": self.metrics.bytes_from_caller
                },
                ai_to_caller={
                    "packets": self.metrics.packets_to_caller,
                    "bytes": self.metrics.bytes_to_caller
                },
                resampling_ops=self.metrics.resampling_operations,
                errors=self.metrics.errors,
                queues={
                    "to_ai": self._to_ai_queue.qsize(),
                    "from_ai": self._from_ai_queue.qsize()
                }
            )
    
    async def __aenter__(self) -> "AudioBridgeWebSocket":
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()
