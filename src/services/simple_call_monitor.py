"""
Простой монитор звонков без зависимостей от DI.
"""

import asyncio
import httpx
from datetime import datetime, timedelta
import structlog

logger = structlog.get_logger()


class SimpleCallMonitor:
    """Простой монитор для проверки звонков через API"""
    
    def __init__(self, api_base_url: str = "http://localhost:8000"):
        self.api_base_url = api_base_url
        self._running = False
        self._task = None
        
    async def start(self):
        """Запуск мониторинга"""
        if self._running:
            return
            
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        await logger.ainfo("Simple call monitor started")
        
    async def stop(self):
        """Остановка мониторинга"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await logger.ainfo("Simple call monitor stopped")
        
    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        async with httpx.AsyncClient() as client:
            while self._running:
                try:
                    # Получаем список активных звонков
                    response = await client.get(f"{self.api_base_url}/api/calls")
                    if response.status_code == 200:
                        data = response.json()
                        calls = data.get("calls", [])
                        
                        for call in calls:
                            await self._check_call(client, call)
                            
                except Exception as e:
                    await logger.aerror(f"Monitor error: {e}")
                    
                await asyncio.sleep(2)  # Проверка каждые 2 секунды
                
    async def _check_call(self, client: httpx.AsyncClient, call: dict):
        """Проверка конкретного звонка"""
        call_id = call.get("id")
        status = call.get("status")
        started_at = call.get("started_at")
        
        if not call_id or not status:
            return
            
        # Проверяем звонки в статусе dialing
        if status == "dialing" and started_at:
            # Парсим время начала
            start_time = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            current_time = datetime.utcnow().replace(tzinfo=start_time.tzinfo)
            duration = (current_time - start_time).total_seconds()
            
            # Если звонит больше 10 секунд - вероятно автоответчик
            if duration > 10:
                await logger.awarning(
                    f"Call {call_id} dialing for {duration:.0f}s - likely operator message, hanging up"
                )
                
                # Завершаем звонок
                try:
                    response = await client.post(
                        f"{self.api_base_url}/api/calls/hangup",
                        params={"call_id": call_id}
                    )
                    if response.status_code == 200:
                        await logger.ainfo(f"Successfully hung up call {call_id}")
                    else:
                        await logger.aerror(f"Failed to hangup call {call_id}: {response.status_code}")
                except Exception as e:
                    await logger.aerror(f"Error hanging up call {call_id}: {e}")
                    
            # Также проверяем общий таймаут в 30 секунд
            elif duration > 30:
                await logger.awarning(f"Call {call_id} timeout after {duration:.0f}s")
                try:
                    await client.post(
                        f"{self.api_base_url}/api/calls/hangup",
                        params={"call_id": call_id}
                    )
                except Exception as e:
                    await logger.aerror(f"Error hanging up call {call_id}: {e}")