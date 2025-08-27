"""
Монитор событий Baresip для обработки SIP статусов.
"""

import asyncio
import json
import httpx
import structlog
from typing import Optional

logger = structlog.get_logger()


class BaresipEventMonitor:
    """
    Мониторит события от Baresip через TCP соединение.
    Обновляет статусы звонков при получении SIP событий.
    """
    
    def __init__(self, host: str = "localhost", port: int = 4444, api_base_url: str = "http://localhost:8000"):
        self.host = host
        self.port = port
        self.api_base_url = api_base_url
        self._running = False
        self._monitor_task = None
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        
    async def start(self):
        """Запуск мониторинга событий Baresip"""
        if self._running:
            return
            
        self._running = True
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        await logger.ainfo("📡 Baresip Event Monitor started - listening for SIP events")
        
    async def stop(self):
        """Остановка мониторинга"""
        self._running = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
                
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            
        await logger.ainfo("Baresip Event Monitor stopped")
        
    async def _connect(self):
        """Подключение к Baresip"""
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host, self.port
            )
            await logger.ainfo(f"Connected to Baresip at {self.host}:{self.port}")
            return True
        except Exception as e:
            await logger.aerror(f"Failed to connect to Baresip: {e}")
            return False
            
    async def _monitor_loop(self):
        """Основной цикл мониторинга событий"""
        while self._running:
            try:
                # Подключаемся если не подключены
                if not self.reader or not self.writer:
                    if not await self._connect():
                        await asyncio.sleep(5)
                        continue
                        
                # Читаем события
                try:
                    data = await asyncio.wait_for(
                        self.reader.read(4096),
                        timeout=5.0
                    )
                    
                    if data:
                        await logger.debug(f"Received data from Baresip: {data[:200]}")
                        await self._process_data(data)
                    else:
                        # Соединение закрыто
                        await logger.awarning("Baresip connection closed, reconnecting...")
                        self.reader = None
                        self.writer = None
                        
                except asyncio.TimeoutError:
                    # Таймаут чтения - это нормально
                    continue
                    
            except Exception as e:
                await logger.aerror(f"Baresip monitor error: {e}")
                await asyncio.sleep(1)
                
    async def _process_data(self, data: bytes):
        """Обработка полученных данных"""
        try:
            response = data.decode('utf-8', errors='ignore')
            
            # Парсим netstring события
            remaining = response
            
            while remaining and ':' in remaining:
                try:
                    colon_idx = remaining.index(':')
                    length_str = remaining[:colon_idx]
                    msg_length = int(length_str)
                    msg_start = colon_idx + 1
                    msg_end = msg_start + msg_length
                    
                    if msg_end <= len(remaining):
                        msg = remaining[msg_start:msg_end]
                        msg_json = json.loads(msg)
                        
                        # Логируем все события
                        if msg_json.get('event'):
                            await logger.debug(f"Parsed event: {msg_json}")
                        
                        # Обрабатываем событие
                        await self._handle_event(msg_json)
                        
                    if msg_end < len(remaining) and remaining[msg_end] == ',':
                        remaining = remaining[msg_end + 1:]
                    else:
                        break
                        
                except (ValueError, json.JSONDecodeError) as e:
                    # Не удалось распарсить - пропускаем
                    break
                    
        except Exception as e:
            await logger.aerror(f"Error processing Baresip data: {e}")
            
    async def _handle_event(self, event: dict):
        """Обработка события от Baresip"""
        if not event.get('event'):
            return
            
        event_type = event.get('type')
        event_class = event.get('class')
        
        # Логируем важные события
        if event_class == 'call':
            if event_type == 'CALL_ESTABLISHED':
                # Это SIP 200 OK - звонок установлен!
                await logger.ainfo("🎉 CALL_ESTABLISHED - SIP 200 OK received!")
                await logger.ainfo(f"Event details: {event}")
                
                # Обновляем статус активного звонка на CONNECTED
                await self._update_active_call_status("connected")
                
            elif event_type == 'CALL_PROGRESS':
                # Это SIP 183 - ранний медиа поток (оператор)
                await logger.ainfo("📢 CALL_PROGRESS - SIP 183 Session Progress (early media)")
                
            elif event_type == 'CALL_RINGING':
                # Это SIP 180 - звонок идёт
                await logger.ainfo("🔔 CALL_RINGING - SIP 180 Ringing")
                
            elif event_type == 'CALL_CLOSED':
                await logger.ainfo(f"📵 Call closed: {event.get('param')}")
                
            elif event_type == 'CALL_FAILED':
                await logger.ainfo(f"❌ Call failed: {event.get('param')}")
                
    async def _update_active_call_status(self, new_status: str):
        """Обновление статуса активного звонка"""
        try:
            async with httpx.AsyncClient() as client:
                # Получаем активный звонок
                response = await client.get(f"{self.api_base_url}/api/calls/active")
                if response.status_code == 200:
                    data = response.json()
                    call = data.get("call")
                    if call:
                        call_id = call.get("id")
                        await logger.ainfo(f"Updating call {call_id} status to {new_status}")
                        
                        # Обновляем статус
                        response = await client.patch(
                            f"{self.api_base_url}/api/calls/{call_id}/status",
                            params={"new_status": new_status}
                        )
                        
                        if response.status_code == 200:
                            await logger.ainfo(f"✅ Call {call_id} status updated to {new_status}")
                        else:
                            await logger.aerror(f"Failed to update call status: {response.status_code}")
                            
        except Exception as e:
            await logger.aerror(f"Error updating call status: {e}")