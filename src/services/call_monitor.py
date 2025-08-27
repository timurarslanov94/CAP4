"""
Мониторинг звонков и обнаружение недоступности абонента.
"""

import asyncio
import re
from typing import Optional, Set
from datetime import datetime, timedelta
import structlog

from src.infrastructure.telephony.baresip_controller import BaresipController
from src.services.call_service import CallService
from src.models.call import CallStatus

logger = structlog.get_logger()


class CallMonitor:
    """Монитор для отслеживания состояния звонков и обнаружения проблем"""
    
    # Паттерны для определения сообщений оператора о недоступности
    UNAVAILABLE_PATTERNS = [
        r"абонент.*недоступен",
        r"абонент.*не.*отвечает",
        r"абонент.*занят",
        r"номер.*не.*существует",
        r"временно.*недоступен",
        r"subscriber.*unavailable",
        r"subscriber.*busy",
        r"number.*does.*not.*exist",
    ]
    
    # Максимальное время ожидания ответа (секунды)
    MAX_RING_TIME = 30
    
    # Время для определения автоответчика после установки соединения
    OPERATOR_MESSAGE_DETECT_TIME = 5
    
    # Максимальная длительность звонка (ElevenLabs лимит)
    MAX_CALL_DURATION = 300  # 5 минут
    
    def __init__(
        self,
        baresip: BaresipController,
        call_service: CallService
    ):
        self.baresip = baresip
        self.call_service = call_service
        self._monitoring_task: Optional[asyncio.Task] = None
        self._running = False
        self._monitored_calls: Set[str] = set()
        
    async def start(self):
        """Запуск мониторинга"""
        if self._running:
            return
            
        self._running = True
        self._monitoring_task = asyncio.create_task(self._monitor_loop())
        await logger.ainfo("Call monitor started")
        
    async def stop(self):
        """Остановка мониторинга"""
        self._running = False
        
        if self._monitoring_task:
            self._monitoring_task.cancel()
            try:
                await self._monitoring_task
            except asyncio.CancelledError:
                pass
            self._monitoring_task = None
            
        await logger.ainfo("Call monitor stopped")
        
    async def _monitor_loop(self):
        """Основной цикл мониторинга"""
        while self._running:
            try:
                await self._check_active_calls()
                await asyncio.sleep(1)  # Проверка каждую секунду
            except Exception as e:
                await logger.aerror(f"Error in monitor loop: {e}")
                await asyncio.sleep(5)
                
    async def _check_active_calls(self):
        """Проверка активных звонков"""
        # Получаем активный звонок
        active_call = await self.call_service.get_active_call()
        if not active_call:
            return
            
        call_id = str(active_call.id)
        
        # Проверяем новые звонки
        if call_id not in self._monitored_calls:
            self._monitored_calls.add(call_id)
            await logger.ainfo(f"Started monitoring call {call_id}")
            
        # Проверяем различные условия для завершения звонка
        await self._check_call_timeout(active_call)
        await self._check_call_duration(active_call)
        await self._check_call_status(active_call)
        
    async def _check_call_timeout(self, call):
        """Проверка таймаута звонка"""
        if call.status != CallStatus.DIALING:
            return
            
        # Проверяем, не слишком ли долго идёт дозвон
        if call.started_at:
            ring_time = (datetime.utcnow() - call.started_at).total_seconds()
            
            if ring_time > self.MAX_RING_TIME:
                await logger.awarning(
                    f"Call {call.id} ringing for too long ({ring_time}s), hanging up"
                )
                await self._hangup_call(call, "No answer - timeout")
    
    async def _check_call_duration(self, call):
        """Проверка максимальной длительности звонка"""
        if call.status != CallStatus.CONNECTED:
            return
            
        # Проверяем длительность активного звонка
        if call.connected_at:
            call_duration = (datetime.utcnow() - call.connected_at).total_seconds()
            
            if call_duration > self.MAX_CALL_DURATION:
                await logger.awarning(
                    f"Call {call.id} exceeded max duration ({call_duration}s), hanging up"
                )
                await self._hangup_call(call, "Max call duration exceeded")
                
    async def _check_call_status(self, call):
        """Проверка статуса звонка через Baresip"""
        try:
            # Получаем информацию о звонке из Baresip
            response = await self.baresip.send_command("l")  # list calls
            
            if response and response.data:
                # Анализируем вывод для определения состояния
                call_info = response.data.lower()
                
                # Проверяем на SIP коды ошибок
                if self._check_sip_errors(call_info):
                    await self._hangup_call(call, "SIP error detected")
                    return
                    
                # SIP 200 OK - абонент действительно ответил
                if "200" in call_info or "established" in call_info:
                    if call.status == CallStatus.DIALING:
                        await logger.ainfo(f"Call {call.id} answered (SIP 200 OK)")
                        await self._on_call_answered(call)
                        
                # SIP 183 Session Progress - это НЕ ответ, это автоответчик оператора
                elif "183" in call_info:
                    if call.status == CallStatus.DIALING:
                        await logger.ainfo(f"Call {call.id} got SIP 183 (Progress) - likely operator message")
                        # Ждём немного и проверяем, не перешёл ли в 200
                        await self._schedule_operator_check(call)
                        
        except Exception as e:
            await logger.aerror(f"Error checking call status: {e}")
            
    def _check_sip_errors(self, call_info: str) -> bool:
        """Проверка на SIP ошибки"""
        error_codes = [
            "404",  # Not Found
            "480",  # Temporarily Unavailable
            "486",  # Busy Here
            "603",  # Decline
            "503",  # Service Unavailable
        ]
        
        for code in error_codes:
            if code in call_info:
                return True
        return False
        
    async def _on_call_answered(self, call):
        """Обработка ответа абонента (SIP 200 OK)"""
        # Обновляем статус на CONNECTED
        await self.call_service.update_call_status(call.id, CallStatus.CONNECTED)
        
        # Теперь можно подключать WebSocket к ElevenLabs
        await logger.ainfo(f"Call {call.id} connected, initiating ElevenLabs WebSocket")
        
        # Подключаем ElevenLabs
        success = await self.call_service.connect_elevenlabs(call.id)
        if not success:
            await logger.aerror(f"Failed to connect ElevenLabs for call {call.id}, hanging up")
            await self._hangup_call(call, "Failed to connect ElevenLabs")
        
    async def _schedule_operator_check(self, call):
        """Планирование проверки на автоответчик оператора при SIP 183"""
        # НЕ обновляем статус на CONNECTED, оставляем DIALING
        # Запускаем таймер для проверки - если через 5 секунд всё ещё 183, то это автоответчик
        asyncio.create_task(self._check_operator_message(call))
        
    async def _check_operator_message(self, call):
        """Проверка на сообщение оператора о недоступности при SIP 183"""
        await asyncio.sleep(self.OPERATOR_MESSAGE_DETECT_TIME)
        
        # Проверяем текущий статус звонка
        response = await self.baresip.send_command("l")
        if response and response.data:
            call_info = response.data.lower()
            
            # Если всё ещё SIP 183 после 5 секунд - это точно автоответчик
            if "183" in call_info:
                await logger.awarning(
                    f"Call {call.id} still in SIP 183 after {self.OPERATOR_MESSAGE_DETECT_TIME}s - operator message detected"
                )
                await self._hangup_call(call, "Operator message detected (SIP 183)")
                return
                
            # Если перешёл в 200 OK - абонент ответил
            if "200" in call_info or "established" in call_info:
                active_call = await self.call_service.get_call(call.id)
                if active_call and active_call.status == CallStatus.DIALING:
                    await logger.ainfo(f"Call {call.id} transitioned from 183 to 200 - real answer")
                    await self._on_call_answered(active_call)
                
    async def _hangup_call(self, call, reason: str):
        """Завершение звонка с указанием причины"""
        try:
            await logger.ainfo(f"Hanging up call {call.id}: {reason}")
            
            # Завершаем через сервис
            await self.call_service.end_call(call.id)
            
            # Убираем из мониторинга
            call_id = str(call.id)
            if call_id in self._monitored_calls:
                self._monitored_calls.remove(call_id)
                
        except Exception as e:
            await logger.aerror(f"Error hanging up call {call.id}: {e}")
            
    def check_text_for_unavailability(self, text: str) -> bool:
        """Проверка текста на паттерны недоступности"""
        if not text:
            return False
            
        text_lower = text.lower()
        
        for pattern in self.UNAVAILABLE_PATTERNS:
            if re.search(pattern, text_lower):
                return True
                
        return False