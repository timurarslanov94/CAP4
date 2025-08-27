from enum import Enum
from typing import Optional

class CallEndReason(str, Enum):
    """Причины завершения звонка"""
    USER_HANGUP = "user_hangup"  # Пользователь завершил звонок
    REMOTE_HANGUP = "remote_hangup"  # Удалённая сторона завершила
    NO_ANSWER = "no_answer"  # Не ответили
    BUSY = "busy"  # Занято
    DECLINED = "declined"  # Отклонён
    UNREACHABLE = "unreachable"  # Недоступен
    NETWORK_ERROR = "network_error"  # Ошибка сети
    TIMEOUT = "timeout"  # Таймаут
    UNKNOWN = "unknown"  # Неизвестная причина


def parse_call_end_reason(baresip_reason: str) -> tuple[CallEndReason, Optional[str]]:
    """
    Парсит причину завершения звонка из сообщения baresip.
    
    Returns:
        Tuple of (reason enum, detailed message)
    """
    reason_lower = baresip_reason.lower()
    
    # SIP response codes and common messages
    if "486" in baresip_reason or "busy" in reason_lower:
        return CallEndReason.BUSY, "Line busy"
    
    elif "603" in baresip_reason or "decline" in reason_lower:
        return CallEndReason.DECLINED, "Call declined"
    
    elif "408" in baresip_reason or "timeout" in reason_lower or "no answer" in reason_lower:
        return CallEndReason.NO_ANSWER, "No answer"
    
    elif "404" in baresip_reason or "not found" in reason_lower:
        return CallEndReason.UNREACHABLE, "Number not found"
    
    elif "480" in baresip_reason or "unavailable" in reason_lower:
        return CallEndReason.UNREACHABLE, "Temporarily unavailable"
    
    elif "503" in baresip_reason or "service unavailable" in reason_lower:
        return CallEndReason.UNREACHABLE, "Service unavailable"
    
    elif "connection reset" in reason_lower or "network" in reason_lower:
        return CallEndReason.NETWORK_ERROR, baresip_reason
    
    elif "user" in reason_lower and "hangup" in reason_lower:
        return CallEndReason.USER_HANGUP, "User ended call"
    
    elif "remote" in reason_lower:
        return CallEndReason.REMOTE_HANGUP, "Remote party ended call"
    
    else:
        return CallEndReason.UNKNOWN, baresip_reason


class CallState(str, Enum):
    """Состояния звонка в системе"""
    INITIATING = "initiating"  # Инициализация
    DIALING = "dialing"  # Набор номера
    RINGING = "ringing"  # Звонит
    CONNECTED = "connected"  # Соединён
    ON_HOLD = "on_hold"  # На удержании
    FAILED = "failed"  # Не удался
    ENDED = "ended"  # Завершён


def map_baresip_event_to_state(event_type: str) -> Optional[CallState]:
    """
    Маппинг событий baresip на состояния звонка.
    """
    event_map = {
        "CALL_OUTGOING": CallState.DIALING,
        "CALL_PROGRESS": CallState.RINGING,
        "CALL_ESTABLISHED": CallState.CONNECTED,
        "CALL_ANSWERED": CallState.CONNECTED,
        "CALL_CLOSED": CallState.ENDED,
    }
    
    return event_map.get(event_type)