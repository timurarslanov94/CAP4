from typing import Optional
from uuid import UUID

from src.models.call import Call, CallUpdate


class CallRepository:
    def __init__(self) -> None:
        self._calls: dict[UUID, Call] = {}
    
    async def save(self, call: Call) -> Call:
        self._calls[call.id] = call
        return call
    
    async def get(self, call_id: UUID) -> Optional[Call]:
        return self._calls.get(call_id)
    
    async def update(self, call_id: UUID, update: CallUpdate) -> Optional[Call]:
        call = self._calls.get(call_id)
        if not call:
            return None
        
        update_data = update.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(call, field, value)
        
        if call.connected_at and call.ended_at:
            call.duration_seconds = int(
                (call.ended_at - call.connected_at).total_seconds()
            )
        
        return call
    
    async def delete(self, call_id: UUID) -> bool:
        if call_id in self._calls:
            del self._calls[call_id]
            return True
        return False
    
    async def list(
        self, 
        limit: int = 100, 
        offset: int = 0
    ) -> list[Call]:
        calls = list(self._calls.values())
        
        calls.sort(key=lambda c: c.started_at or c.id, reverse=True)
        
        return calls[offset:offset + limit]
    
    async def count(self) -> int:
        return len(self._calls)