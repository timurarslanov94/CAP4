"""
SIP Call Monitor - мониторинг SIP событий и управление WebSocket подключением.
Подключает ElevenLabs WebSocket ТОЛЬКО при получении SIP 200 OK (реальный ответ).
"""

import asyncio
import httpx
import json
from typing import Optional
from datetime import datetime
import structlog

logger = structlog.get_logger()


class SIPCallMonitor:
    """
    Монитор SIP событий через Baresip.
    Отслеживает SIP статусы и управляет подключением к ElevenLabs.
    """
    
    def __init__(self, api_base_url: str = "http://localhost:8000"):
        self.api_base_url = api_base_url
        self._running = False
        self._monitor_task = None
        self._active_calls = {}  # call_id -> call_info
        
    async def start(self):
        """Запуск мониторинга"""
        if self._running:
            return
            
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        await logger.ainfo("🎯 SIP Call Monitor started - will connect WebSocket only on SIP 200 OK")
        
    async def stop(self):
        """Остановка мониторинга"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        await logger.ainfo("SIP Call Monitor stopped")
        
    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        async with httpx.AsyncClient() as client:
            while self._running:
                try:
                    # Получаем активные звонки
                    response = await client.get(f"{self.api_base_url}/api/calls")
                    if response.status_code == 200:
                        data = response.json()
                        calls = data.get("calls", [])
                        
                        for call in calls:
                            await self._check_call_status(client, call)
                            
                except Exception as e:
                    await logger.aerror(f"SIP monitor error: {e}")
                    
                await asyncio.sleep(2)  # Проверка каждые 2 секунды
                
    async def _check_call_status(self, client: httpx.AsyncClient, call: dict):
        """Проверка статуса звонка и SIP событий"""
        call_id = call.get("id")
        status = call.get("status")
        
        if not call_id or not status:
            return
        
        # Отслеживаем новые звонки в статусе dialing
        if status == "dialing":
            if call_id not in self._active_calls:
                self._active_calls[call_id] = {
                    "started_at": datetime.utcnow(),
                    "sip_status": None,
                    "websocket_connected": False
                }
                await logger.ainfo(f"📞 Tracking new call {call_id} - waiting for SIP response")
            
            # Проверяем длительность звонка
            call_info = self._active_calls[call_id]
            duration = (datetime.utcnow() - call_info["started_at"]).total_seconds()
            
            # Если звонит больше 10 секунд - просто логируем
            if duration > 10 and not call_info.get("websocket_connected"):
                # Убираем спам в логах - CallService сам решит когда подключать WebSocket
                pass
                
                # После 30 секунд завершаем (увеличили с 15 до 30)
                if duration > 30:
                    await logger.awarning(f"❌ Hanging up call {call_id} - timeout, no real answer")
                    try:
                        response = await client.post(
                            f"{self.api_base_url}/api/calls/hangup",
                            params={"call_id": call_id}
                        )
                        if response.status_code == 200:
                            await logger.ainfo(f"✅ Successfully hung up call {call_id}")
                            del self._active_calls[call_id]
                    except Exception as e:
                        await logger.aerror(f"Error hanging up call {call_id}: {e}")
                        
        # Если статус изменился на connected - это SIP 200 OK!
        elif status == "connected":
            if call_id in self._active_calls:
                call_info = self._active_calls[call_id]
                if not call_info.get("websocket_connected"):
                    await logger.ainfo(f"🎉 Call {call_id} CONNECTED - SIP 200 OK received!")
                    await logger.ainfo(f"📞 Real person answered the call!")
                    await logger.ainfo(f"🔌 NOW connecting ElevenLabs WebSocket for call {call_id}")
                    
                    # Здесь должен вызываться connect_elevenlabs через CallService
                    # Но так как мы работаем через API, нужно отправить команду
                    await self._connect_websocket_for_call(client, call_id)
                    
                    call_info["websocket_connected"] = True
                    call_info["sip_status"] = "200 OK"
                    
        # Удаляем завершённые звонки из отслеживания
        elif status in ["completed", "failed"]:
            if call_id in self._active_calls:
                await logger.ainfo(f"Call {call_id} ended with status: {status}")
                del self._active_calls[call_id]
                
    async def _connect_websocket_for_call(self, client: httpx.AsyncClient, call_id: str):
        """Подключение WebSocket для конкретного звонка"""
        try:
            # Вызываем эндпоинт для подключения WebSocket
            response = await client.post(
                f"{self.api_base_url}/api/calls/{call_id}/connect_elevenlabs"
            )
            
            if response.status_code == 200:
                await logger.ainfo(f"✅ ElevenLabs WebSocket connected for call {call_id}")
            else:
                await logger.aerror(
                    f"Failed to connect WebSocket for call {call_id}: {response.status_code}"
                )
            
        except Exception as e:
            await logger.aerror(f"Failed to connect WebSocket for call {call_id}: {e}")