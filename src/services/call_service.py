import asyncio
from datetime import datetime
from typing import Optional
from uuid import UUID

import structlog

from src.models.call import (
    Call, 
    CallCreate, 
    CallStatus, 
    CallDirection,
    CallUpdate
)
from src.infrastructure.telephony.baresip_controller import BaresipController
from src.infrastructure.audio.audio_bridge import AudioBridge, AudioFrame
from src.infrastructure.ai.elevenlabs_client import ElevenLabsClient
from src.repositories.call_repository import CallRepository


logger = structlog.get_logger()


class CallService:
    def __init__(
        self,
        baresip_controller: BaresipController,
        audio_bridge: AudioBridge,
        elevenlabs_client: ElevenLabsClient,
        call_repository: CallRepository
    ) -> None:
        self.baresip = baresip_controller
        self.audio_bridge = audio_bridge
        self.elevenlabs = elevenlabs_client
        self.repository = call_repository
        
        self._active_call: Optional[Call] = None
        self._audio_tasks: list[asyncio.Task] = []
        
    async def start_call(self, call_data: CallCreate) -> Call:
        if self._active_call and self._active_call.status in [
            CallStatus.DIALING, 
            CallStatus.RINGING, 
            CallStatus.CONNECTED
        ]:
            raise ValueError("Another call is already in progress")
        
        call = Call(
            phone_number=call_data.phone_number,
            direction=CallDirection.OUTBOUND,
            status=CallStatus.DIALING,
            started_at=datetime.utcnow(),
            agent_prompt=None,
            metadata={}
        )
        
        self._active_call = call
        await self.repository.save(call)
        
        try:
            await self.baresip.connect()
            
            dial_response = await self.baresip.dial(call.phone_number)
            if not dial_response.success:
                raise Exception(f"Failed to dial: {dial_response.error}")
            
            # AudioBridge уже запущен отдельным процессом (run_audio_bridge.py)
            # Не нужно запускать его здесь, иначе будет конфликт!
            await logger.ainfo("Audio bridge already running externally, skipping transport start")
            
            # Пока без аудио задач
            self._audio_tasks = []
            
            await logger.ainfo("Audio transport ready, will connect WebSocket when call is answered")
            
            # Запускаем мониторинг событий звонка
            asyncio.create_task(self._monitor_call_events(call.id))
            
            # Оставляем статус DIALING пока не получим реальный ответ
            call.status = CallStatus.DIALING
            await self.repository.update(call.id, CallUpdate(
                status=call.status,
                connected_at=call.connected_at
            ))
            
            await logger.ainfo(
                "Call started successfully",
                call_id=str(call.id),
                phone_number=call.phone_number
            )
            
        except Exception as e:
            call.status = CallStatus.FAILED
            call.error = str(e)
            call.ended_at = datetime.utcnow()
            await self.repository.update(call.id, CallUpdate(
                status=call.status,
                error=call.error,
                ended_at=call.ended_at
            ))
            
            await self._cleanup()
            
            await logger.aerror(
                "Failed to start call",
                call_id=str(call.id),
                error=str(e)
            )
            raise
        
        return call
    
    async def connect_elevenlabs(self, call_id: UUID) -> bool:
        """Подключение к ElevenLabs WebSocket при реальном ответе абонента"""
        if not self._active_call or self._active_call.id != call_id:
            await logger.aerror(f"Cannot connect ElevenLabs - call {call_id} is not active")
            return False
            
        try:
            await logger.ainfo(f"Connecting to ElevenLabs for call {call_id}")
            
            # Подключаем ElevenLabs
            await self.elevenlabs.connect()
            
            # Запускаем WebSocket аудио моста (транспорт уже должен быть запущен)
            # ВАЖНО: используем start_websocket(), а НЕ start()!
            await self.audio_bridge.start_websocket()
            
            # Настраиваем маршрутизацию аудио
            self._setup_audio_routing()
            
            await logger.ainfo(f"ElevenLabs connected successfully for call {call_id}")
            return True
            
        except Exception as e:
            await logger.aerror(f"Failed to connect ElevenLabs for call {call_id}: {e}")
            return False
    
    async def update_call_status(self, call_id: UUID, status: CallStatus) -> Optional[Call]:
        """Обновление статуса звонка"""
        call = await self.repository.get(call_id)
        if not call:
            return None
            
        call.status = status
        
        # Обновляем временные метки в зависимости от статуса
        if status == CallStatus.CONNECTED and not call.connected_at:
            call.connected_at = datetime.utcnow()
        elif status in [CallStatus.COMPLETED, CallStatus.FAILED] and not call.ended_at:
            call.ended_at = datetime.utcnow()
            if call.connected_at:
                call.duration_seconds = int(
                    (call.ended_at - call.connected_at).total_seconds()
                )
                
        await self.repository.update(call.id, CallUpdate(
            status=status,
            connected_at=call.connected_at,
            ended_at=call.ended_at,
            duration_seconds=call.duration_seconds
        ))
        
        # Обновляем активный звонок, если это он
        if self._active_call and self._active_call.id == call_id:
            self._active_call = call
            
        return call
    
    async def end_call(self, call_id: Optional[UUID] = None) -> Optional[Call]:
        import os
        # Если указан конкретный call_id
        if call_id:
            # Проверяем, это активный звонок или нет
            if self._active_call and self._active_call.id == call_id:
                # Это активный звонок - завершаем через Baresip
                call = self._active_call
            else:
                # Это другой звонок - просто обновляем в БД
                call = await self.repository.get(call_id)
                if not call:
                    return None
                    
            # Завершаем звонок
            if call == self._active_call:
                await self.baresip.hangup()
                
                # Создаём файл-сигнал для отключения WebSocket
                await logger.ainfo("📵 Creating WebSocket disconnect signal...")
                with open("/tmp/disconnect_websocket", "w") as f:
                    f.write(str(call_id))
                await logger.ainfo("✅ Signal sent to disconnect WebSocket!")
                
                self._active_call = None
                
            call.status = CallStatus.COMPLETED
            call.ended_at = datetime.utcnow()
            if call.connected_at:
                call.duration_seconds = int(
                    (call.ended_at - call.connected_at).total_seconds()
                )
            else:
                call.duration_seconds = 0
                
            await self.repository.update(call.id, CallUpdate(
                status=call.status,
                ended_at=call.ended_at,
                duration_seconds=call.duration_seconds
            ))
            
            await self._cleanup()
            return call
        
        # Если call_id не указан - завершаем активный звонок
        if not self._active_call:
            return None
        
        call = self._active_call
        
        await self.baresip.hangup()
        
        # Создаём файл-сигнал для отключения WebSocket
        await logger.ainfo("📵 Creating WebSocket disconnect signal...")
        with open("/tmp/disconnect_websocket", "w") as f:
            f.write(str(call.id))
        await logger.ainfo("✅ Signal sent to disconnect WebSocket!")
        
        call.status = CallStatus.COMPLETED
        call.ended_at = datetime.utcnow()
        if call.connected_at:
            call.duration_seconds = int(
                (call.ended_at - call.connected_at).total_seconds()
            )
        
        await self.repository.update(call.id, CallUpdate(
            status=call.status,
            ended_at=call.ended_at
        ))
        
        await self._cleanup()
        
        await logger.ainfo(
            "Call ended",
            call_id=str(call.id),
            duration=call.duration_seconds
        )
        
        self._active_call = None
        return call
    
    async def get_call(self, call_id: UUID) -> Optional[Call]:
        return await self.repository.get(call_id)
    
    async def list_calls(
        self, 
        limit: int = 100, 
        offset: int = 0
    ) -> list[Call]:
        return await self.repository.list(limit=limit, offset=offset)
    
    async def get_active_call(self) -> Optional[Call]:
        return self._active_call
    
    def _setup_audio_routing(self) -> None:
        self.elevenlabs.set_audio_callback(self._on_elevenlabs_audio)
        
        self.elevenlabs.set_transcript_callback(self._on_transcript)
    
    def _on_elevenlabs_audio(self, frame: AudioFrame) -> None:
        asyncio.create_task(self.audio_bridge.write_frame(frame))
    
    def _on_transcript(self, text: str, is_user: bool) -> None:
        source = "User" if is_user else "Agent"
        asyncio.create_task(logger.ainfo(
            f"{source} transcript",
            text=text,
            call_id=str(self._active_call.id) if self._active_call else None
        ))
    
    async def _audio_input_loop(self) -> None:
        while self._active_call and self._active_call.status == CallStatus.CONNECTED:
            try:
                frame = await self.audio_bridge.read_frame()
                if frame:
                    await self.elevenlabs.send_audio(frame)
                else:
                    await asyncio.sleep(0.01)
            except Exception as e:
                await logger.aerror("Error in audio input loop", error=str(e))
                break
    
    async def _audio_output_loop(self) -> None:
        while self._active_call and self._active_call.status == CallStatus.CONNECTED:
            await asyncio.sleep(0.1)
    
    async def _monitor_call_events(self, call_id: UUID) -> None:
        """Мониторинг событий звонка для определения SIP статусов"""
        import os
        
        websocket_connected = False
        
        async def handle_event(event: dict) -> None:
            """Callback для немедленной обработки событий"""
            nonlocal websocket_connected
            
            event_type = event.get('type')
            await logger.ainfo(f"📨 Real-time event: {event_type}")
            
            if event_type == 'CALL_ESTABLISHED':
                # SIP 200 OK - реальный ответ абонента!
                await logger.ainfo("=" * 50)
                await logger.ainfo(f"🎉 CALL_ESTABLISHED (SIP 200 OK) detected!")
                await logger.ainfo(f"✅ Real person answered the call {call_id}")
                await logger.ainfo("🔌 Connecting ElevenLabs WebSocket IMMEDIATELY...")
                await logger.ainfo("=" * 50)
                
                # НЕМЕДЛЕННО обновляем статус звонка
                await self.update_call_status(call_id, CallStatus.CONNECTED)
                
                # НЕМЕДЛЕННО создаём файл-сигнал для подключения WebSocket
                with open("/tmp/connect_websocket", "w") as f:
                    f.write(str(call_id))
                await logger.ainfo("✅ WebSocket connection signal sent INSTANTLY!")
                
                websocket_connected = True
                
            elif event_type == 'CALL_PROGRESS':
                # SIP 183 - сообщение оператора
                await logger.ainfo("=" * 50)
                await logger.ainfo(f"📢 CALL_PROGRESS (SIP 183) detected")
                await logger.ainfo("⚠️  This is an operator/voicemail message")
                await logger.ainfo("❌ NOT connecting WebSocket (saving ElevenLabs credits)")
                await logger.ainfo("=" * 50)
                
            elif event_type in ['CALL_CLOSED', 'CALL_FAILED']:
                # Звонок завершён
                await logger.ainfo(f"📵 Call {call_id} ended: {event_type}")
                
                if websocket_connected:
                    # Если WebSocket был подключен - отключаем
                    await logger.ainfo("🔌 Disconnecting WebSocket to save credits...")
                    with open("/tmp/disconnect_websocket", "w") as f:
                        f.write(str(call_id))
                    await logger.ainfo("✅ WebSocket disconnect signal sent!")
                
                # НЕ вызываем end_call здесь, так как звонок уже завершён
        
        try:
            await logger.ainfo(f"📡 Starting REAL-TIME monitoring for call {call_id}")
            await logger.ainfo("⏳ Events will be processed IMMEDIATELY as they arrive:")
            await logger.ainfo("   - SIP 183 (CALL_PROGRESS) = operator message → NO WebSocket")
            await logger.ainfo("   - SIP 200 (CALL_ESTABLISHED) = real answer → CONNECT WebSocket instantly")
            
            # Мониторим события с НЕМЕДЛЕННЫМ callback
            events = await self.baresip.monitor_call_events(
                timeout=60.0,
                callback=handle_event  # Обрабатываем события СРАЗУ при получении!
            )
            
            await logger.ainfo(f"Monitoring completed, processed {len(events)} events in real-time")
                    
        except asyncio.TimeoutError:
            await logger.aerror(f"⏰ Call monitoring timeout for {call_id} - no answer after 60 seconds")
            if self._active_call and self._active_call.id == call_id:
                await self.end_call(call_id)
        except Exception as e:
            await logger.aerror(f"Error monitoring call events: {e}")
    
    async def _cleanup(self) -> None:
        for task in self._audio_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        self._audio_tasks.clear()
        
        # Временно отключаем очистку аудио компонентов
        # await self.audio_bridge.stop()
        # await self.elevenlabs.disconnect()
        await self.baresip.disconnect()