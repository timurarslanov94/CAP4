from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from src.models.call_status import CallEndReason


class CallStatus(str, Enum):
    IDLE = "idle"
    DIALING = "dialing"
    RINGING = "ringing"
    CONNECTED = "connected"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    FAILED = "failed"


class CallDirection(str, Enum):
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class CallCreate(BaseModel):
    phone_number: str = Field(..., description="Phone number to call")


class Call(BaseModel):
    id: UUID = Field(default_factory=uuid4, description="Unique call identifier")
    phone_number: str = Field(..., description="Phone number")
    direction: CallDirection = Field(..., description="Call direction")
    status: CallStatus = Field(default=CallStatus.IDLE, description="Current call status")
    started_at: Optional[datetime] = Field(None, description="Call start time")
    connected_at: Optional[datetime] = Field(None, description="Call connection time")
    ended_at: Optional[datetime] = Field(None, description="Call end time")
    duration_seconds: Optional[int] = Field(None, description="Call duration in seconds")
    agent_prompt: Optional[str] = Field(None, description="AI agent prompt")
    metadata: dict = Field(default_factory=dict, description="Additional metadata")
    error: Optional[str] = Field(None, description="Error message if call failed")
    end_reason: Optional[CallEndReason] = Field(None, description="Reason for call ending")
    end_reason_details: Optional[str] = Field(None, description="Detailed end reason")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }


class CallUpdate(BaseModel):
    status: Optional[CallStatus] = None
    connected_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: Optional[dict] = None


class CallResponse(BaseModel):
    call: Call
    message: str = Field(..., description="Response message")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }


class CallListResponse(BaseModel):
    calls: list[Call]
    total: int = Field(..., description="Total number of calls")
    
    class Config:
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            UUID: lambda v: str(v)
        }