from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import structlog

from src.api.routers import calls
from src.core.config import get_settings
from src.core.di import setup_di
# SIPCallMonitor отключён - события мониторятся напрямую через Baresip TCP


logger = structlog.get_logger()

# SIPCallMonitor больше не используется
# События от Baresip обрабатываются напрямую в CallService._monitor_call_events()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await logger.ainfo("Starting Voice AI Agent API")
    
    # ВАЖНО: HTTP polling через SIPCallMonitor отключён!
    # События SIP мониторятся напрямую через Baresip TCP в CallService._monitor_call_events()
    # Это устраняет:
    # - Избыточные HTTP запросы каждые 2 секунды
    # - Циклическую зависимость (API опрашивал сам себя)
    # - Задержки в обработке событий
    await logger.ainfo("✅ API started - SIP events monitored directly via Baresip TCP")
    await logger.ainfo("📡 Call events flow: Baresip TCP → CallService → WebSocket signals → AudioBridge")
    
    yield
    
    await logger.ainfo("Shutting down Voice AI Agent API")


def create_app() -> FastAPI:
    settings = get_settings()
    
    app = FastAPI(
        title="Voice AI Agent",
        description="AI-powered voice agent with baresip and ElevenLabs integration",
        version="0.1.0",
        debug=settings.debug,
        lifespan=lifespan
    )
    
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Настройка Dishka DI
    setup_di(app)
    
    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "service": "voice-ai-agent"
        }
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        await logger.aerror(
            "Unhandled exception",
            path=request.url.path,
            method=request.method,
            error=str(exc)
        )
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "error": str(exc) if settings.debug else "An error occurred"
            }
        )
    
    app.include_router(calls.router)
    
    return app


app = create_app()