import asyncio
import sys
from pathlib import Path

import uvicorn
import structlog

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.core.config import get_settings
from src.api.app import app  # Export app for uvicorn


def configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer()
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def main() -> None:
    configure_logging()
    settings = get_settings()
    
    uvicorn.run(
        "src.api.app:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )


# Export app for uvicorn to find it
__all__ = ["app"]

if __name__ == "__main__":
    main()