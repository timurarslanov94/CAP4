import asyncio
import json
import logging
from typing import Optional, Any, List
from dataclasses import dataclass
from enum import Enum

import structlog

from src.core.config import BaresipConfig
from src.models.call_status import parse_call_end_reason, map_baresip_event_to_state


logger = structlog.get_logger()


class BaresipCommand(str, Enum):
    DIAL = "dial"  # Полная команда для dial
    HANGUP = "hangup"  # Полная команда для hangup
    ANSWER = "accept"  # Полная команда для answer
    MUTE = "mute"
    UNMUTE = "unmute"
    HOLD = "hold"
    RESUME = "resume"
    LIST_CALLS = "listcalls"
    REG_INFO = "reginfo"


@dataclass
class BaresipResponse:
    success: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    events: Optional[List[dict[str, Any]]] = None  # Все события из ответа


class BaresipController:
    def __init__(self, config: BaresipConfig) -> None:
        self.config = config
        self.host = config.host  # ВАЖНО: сохраняем host для monitor_call_events
        self.port = config.ctrl_tcp_port  # ВАЖНО: используем правильное имя поля!
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self._connected = False
        self._lock = asyncio.Lock()
        
    async def connect(self) -> None:
        if self._connected:
            return
            
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.config.host, 
                self.config.ctrl_tcp_port
            )
            self._connected = True
            await logger.ainfo(
                "Connected to baresip",
                host=self.config.host,
                port=self.config.ctrl_tcp_port
            )
        except Exception as e:
            await logger.aerror(
                "Failed to connect to baresip",
                host=self.config.host,
                port=self.config.ctrl_tcp_port,
                error=str(e)
            )
            raise
    
    async def disconnect(self) -> None:
        if not self._connected:
            return
            
        if self.writer:
            self.writer.close()
            await self.writer.wait_closed()
            
        self._connected = False
        await logger.ainfo("Disconnected from baresip")
    
    async def send_command(
        self, 
        command: BaresipCommand, 
        params: Optional[str] = None
    ) -> BaresipResponse:
        async with self._lock:
            if not self._connected:
                await self.connect()
            
            try:
                # Baresip ctrl_tcp expects netstring format with JSON inside
                cmd_json = {
                    "command": command.value,
                }
                if params:
                    cmd_json["params"] = params
                
                cmd_str = json.dumps(cmd_json)
                
                # Create proper netstring: count bytes, not characters
                cmd_bytes = cmd_str.encode('utf-8')
                length = len(cmd_bytes)
                netstring = f"{length}:".encode('utf-8') + cmd_bytes + b","
                
                await logger.adebug("Sending netstring command to baresip", 
                                   json=cmd_str, 
                                   netstring=netstring.decode('utf-8', errors='ignore'))
                
                # Send netstring
                self.writer.write(netstring)
                await self.writer.drain()
                
                # Read response with netstring format
                response_data = await asyncio.wait_for(
                    self.reader.read(4096),
                    timeout=3.0
                )
                
                if response_data:
                    response = response_data.decode('utf-8', errors='ignore')
                    await logger.adebug("Received response from baresip", response=response)
                    
                    # Parse multiple netstring messages
                    messages = []
                    remaining = response
                    
                    while remaining and ':' in remaining:
                        try:
                            # Find the length part
                            colon_idx = remaining.index(':')
                            length_str = remaining[:colon_idx]
                            
                            # Parse length
                            try:
                                msg_length = int(length_str)
                            except ValueError:
                                break
                            
                            # Extract the message
                            msg_start = colon_idx + 1
                            msg_end = msg_start + msg_length
                            
                            if msg_end > len(remaining):
                                break
                                
                            msg = remaining[msg_start:msg_end]
                            
                            # Parse JSON
                            try:
                                msg_json = json.loads(msg)
                                messages.append(msg_json)
                            except json.JSONDecodeError:
                                pass
                            
                            # Move past the comma
                            if msg_end < len(remaining) and remaining[msg_end] == ',':
                                remaining = remaining[msg_end + 1:]
                            else:
                                break
                                
                        except (ValueError, IndexError):
                            break
                    
                    # Separate events and responses
                    events = [msg for msg in messages if msg.get('event')]
                    responses = [msg for msg in messages if msg.get('response')]
                    
                    # Find the most important event
                    priority_event = None
                    for event in events:
                        event_type = event.get('type')
                        if event_type in ['CALL_CLOSED', 'CALL_FAILED']:
                            # Highest priority - call ended
                            priority_event = event
                            break
                        elif event_type in ['CALL_ESTABLISHED', 'CALL_ANSWERED']:
                            # High priority - call connected
                            priority_event = event
                        elif event_type == 'CALL_OUTGOING' and not priority_event:
                            # Lower priority - call started
                            priority_event = event
                    
                    # If we have a response, check if it's successful
                    if responses:
                        resp = responses[0]
                        if not resp.get('ok'):
                            return BaresipResponse(
                                success=False,
                                error=resp.get('data', 'Command failed'),
                                events=events
                            )
                    
                    # Return priority event or first event/response
                    if priority_event:
                        return BaresipResponse(
                            success=True,
                            data=priority_event,
                            events=events
                        )
                    elif messages:
                        return BaresipResponse(
                            success=True,
                            data=messages[0],
                            events=events
                        )
                    
                return BaresipResponse(
                    success=True,
                    data={"status": "sent"}
                )
                    
            except asyncio.TimeoutError:
                error_msg = f"Command timeout: {command.value}"
                await logger.aerror(error_msg)
                return BaresipResponse(success=False, error=error_msg)
            except Exception as e:
                error_msg = f"Command failed: {str(e)}"
                await logger.aerror(error_msg, command=command.value)
                return BaresipResponse(success=False, error=error_msg)
    
    async def dial(self, number: str, ua_index: int = 0) -> BaresipResponse:
        # Remove + from number if present
        clean_number = number.lstrip('+')
        
        # Try different formats based on Baresip version
        # Some versions need: "/ua dial <sip:number@domain>"
        # Others need: "/dial <number>" or "/dial sip:number@domain"
        
        # Format 1: Full SIP URI (most common)
        sip_uri = f"sip:{clean_number}@{self.config.sip_domain}"
        
        await logger.ainfo(f"Attempting to dial: {sip_uri}")
        
        # First try with SIP URI
        response = await self.send_command(BaresipCommand.DIAL, sip_uri)
        
        if not response.success and "could not find UA" in response.error:
            # If it fails with "could not find UA", try with just the number
            await logger.ainfo(f"SIP URI failed, trying with just number: {clean_number}")
            response = await self.send_command(BaresipCommand.DIAL, clean_number)
            
            if not response.success:
                # Last resort: try with UA index prefix
                dial_with_ua = f"{ua_index} {sip_uri}"
                await logger.ainfo(f"Plain number failed, trying with UA index: {dial_with_ua}")
                response = await self.send_command(BaresipCommand.DIAL, dial_with_ua)
        
        return response
    
    async def hangup(self) -> BaresipResponse:
        return await self.send_command(BaresipCommand.HANGUP)
    
    async def answer(self) -> BaresipResponse:
        return await self.send_command(BaresipCommand.ANSWER)
    
    async def mute(self, enable: bool = True) -> BaresipResponse:
        command = BaresipCommand.MUTE if enable else BaresipCommand.UNMUTE
        return await self.send_command(command)
    
    async def hold(self, enable: bool = True) -> BaresipResponse:
        command = BaresipCommand.HOLD if enable else BaresipCommand.RESUME
        return await self.send_command(command)
    
    async def list_calls(self) -> BaresipResponse:
        return await self.send_command(BaresipCommand.LIST_CALLS)
    
    async def get_registration_info(self) -> BaresipResponse:
        return await self.send_command(BaresipCommand.REG_INFO)
    
    async def monitor_call_events(self, timeout: float = 60.0, callback=None) -> List[dict[str, Any]]:
        """
        Мониторит события звонка в реальном времени.
        Использует отдельное соединение для мониторинга.
        
        Args:
            timeout: Максимальное время мониторинга в секундах
            callback: Опциональная функция для немедленной обработки событий
        """
        await logger.ainfo(f"🔍 Starting real-time call event monitoring (timeout: {timeout}s)")
        
        # Создаём отдельное соединение для мониторинга
        try:
            monitor_reader, monitor_writer = await asyncio.open_connection(
                self.host, self.port
            )
            await logger.ainfo("✅ Created separate connection for event monitoring")
        except Exception as e:
            await logger.aerror(f"Failed to create monitoring connection: {e}")
            return []
        
        events = []
        start_time = asyncio.get_event_loop().time()
        call_established = False
        
        try:
            while (asyncio.get_event_loop().time() - start_time) < timeout:
                try:
                    # Читаем данные с небольшим таймаутом из отдельного соединения
                    data = await asyncio.wait_for(
                        monitor_reader.read(4096),
                        timeout=0.5  # Уменьшили таймаут для более быстрой реакции
                    )
                    
                    if data:
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
                                    
                                    if msg_json.get('event'):
                                        event_type = msg_json.get('type')
                                        param = msg_json.get('param', '')
                                        
                                        # Детальное логирование событий
                                        if event_type == 'CALL_ESTABLISHED':
                                            await logger.ainfo("=" * 60)
                                            await logger.ainfo("🎉 CALL_ESTABLISHED - SIP 200 OK!")
                                            await logger.ainfo(f"   → Call ID/Param: {param}")
                                            await logger.ainfo("   → Real person answered the phone")
                                            await logger.ainfo("   → WebSocket should be connected NOW")
                                            await logger.ainfo("=" * 60)
                                            call_established = True
                                            
                                        elif event_type == 'CALL_PROGRESS':
                                            await logger.ainfo("=" * 60)
                                            await logger.ainfo("📢 CALL_PROGRESS - SIP 183 Session Progress")
                                            await logger.ainfo(f"   → Param: {param}")
                                            await logger.ainfo("   → This is operator/voicemail message")
                                            await logger.ainfo("   → WebSocket should NOT be connected")
                                            await logger.ainfo("=" * 60)
                                            
                                        elif event_type == 'CALL_RINGING':
                                            await logger.ainfo(f"🔔 CALL_RINGING - Phone is ringing (param: {param})")
                                            
                                        elif event_type == 'CALL_OUTGOING':
                                            await logger.ainfo(f"📞 CALL_OUTGOING - Initiating call (param: {param})")
                                            
                                        else:
                                            await logger.ainfo(f"📡 Baresip event: {event_type} (param: {param})")
                                        
                                        events.append(msg_json)
                                        
                                        # Вызываем callback если задан
                                        if callback:
                                            await callback(msg_json)
                                        
                                        # Продолжаем мониторинг после CALL_ESTABLISHED для отслеживания завершения
                                        # Не прерываем цикл сразу
                                        
                                        # Если звонок завершён, прекращаем мониторинг
                                        if event_type in ['CALL_CLOSED', 'CALL_FAILED']:
                                            await logger.ainfo("=" * 60)
                                            await logger.ainfo(f"📵 Call ended: {event_type}")
                                            await logger.ainfo(f"   → Param: {param}")
                                            if call_established:
                                                await logger.ainfo("   → WebSocket should be disconnected")
                                            await logger.ainfo("=" * 60)
                                            return events
                                
                                if msg_end < len(remaining) and remaining[msg_end] == ',':
                                    remaining = remaining[msg_end + 1:]
                                else:
                                    break
                            except (ValueError, json.JSONDecodeError) as e:
                                await logger.adebug(f"Failed to parse event: {e}")
                                break
                
                except asyncio.TimeoutError:
                    # Продолжаем ждать события
                    continue
                    
        except Exception as e:
            await logger.aerror("Error monitoring call events", error=str(e))
        finally:
            # Закрываем отдельное соединение для мониторинга
            try:
                monitor_writer.close()
                await monitor_writer.wait_closed()
                await logger.ainfo("✅ Closed monitoring connection")
            except:
                pass
        
        await logger.ainfo(f"⏱️ Event monitoring completed. Found {len(events)} events")
        if not call_established and len(events) > 0:
            await logger.awarning("⚠️ No CALL_ESTABLISHED event received - call was not answered by a real person")
        
        return events
    
    async def __aenter__(self) -> "BaresipController":
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()