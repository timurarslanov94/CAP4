from typing import Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, status, Query
from dishka import FromDishka
from dishka.integrations.fastapi import inject

from src.models.call import (
    CallCreate, 
    CallResponse, 
    CallListResponse,
    CallStatus
)
from src.services.call_service import CallService


router = APIRouter(prefix="/api/calls", tags=["calls"])


@router.post("/start", response_model=CallResponse)
@inject
async def start_call(
    call_data: CallCreate,
    call_service: FromDishka[CallService]
) -> CallResponse:
    try:
        call = await call_service.start_call(call_data)
        return CallResponse(
            call=call,
            message="Call started successfully"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start call: {str(e)}"
        )


@router.post("/hangup", response_model=CallResponse)
@inject
async def hangup_call(
    call_id: Optional[UUID] = Query(None, description="Call ID to hangup, if None - hangs up active call"),
    call_service: FromDishka[CallService] = None
) -> CallResponse:
    call = await call_service.end_call(call_id)
    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active call found"
        )
    
    return CallResponse(
        call=call,
        message="Call ended successfully"
    )


@router.get("/active", response_model=CallResponse)
@inject
async def get_active_call(
    call_service: FromDishka[CallService]
) -> CallResponse:
    call = await call_service.get_active_call()
    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active call"
        )
    
    return CallResponse(
        call=call,
        message="Active call retrieved"
    )


@router.get("/{call_id}", response_model=CallResponse)
@inject
async def get_call(
    call_id: UUID,
    call_service: FromDishka[CallService]
) -> CallResponse:
    call = await call_service.get_call(call_id)
    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Call {call_id} not found"
        )
    
    return CallResponse(
        call=call,
        message="Call retrieved successfully"
    )


@router.get("", response_model=CallListResponse)
@inject
async def list_calls(
    limit: int = 100,
    offset: int = 0,
    call_service: FromDishka[CallService] = None
) -> CallListResponse:
    calls = await call_service.list_calls(limit=limit, offset=offset)
    return CallListResponse(
        calls=calls,
        total=len(calls)
    )


@router.post("/{call_id}/connect_elevenlabs")
@inject
async def connect_elevenlabs(
    call_id: UUID,
    call_service: FromDishka[CallService]
) -> dict:
    """Подключение ElevenLabs WebSocket для конкретного звонка (вызывается при SIP 200 OK)"""
    success = await call_service.connect_elevenlabs(call_id)
    if success:
        return {
            "status": "success",
            "message": f"ElevenLabs WebSocket connected for call {call_id}"
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to connect ElevenLabs for call {call_id}"
        )


@router.patch("/{call_id}/status")
@inject
async def update_call_status(
    call_id: UUID,
    new_status: CallStatus,
    call_service: FromDishka[CallService]
) -> CallResponse:
    """Обновление статуса звонка (используется мониторами)"""
    call = await call_service.update_call_status(call_id, new_status)
    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Call {call_id} not found"
        )
    
    return CallResponse(
        call=call,
        message=f"Call status updated to {new_status}"
    )