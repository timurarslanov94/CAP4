#!/usr/bin/env python3
"""
Запуск аудио моста между Baresip и ElevenLabs.
Должен быть запущен ДО старта Baresip!
"""

import asyncio
import signal
import sys
from pathlib import Path
from datetime import datetime

# Добавляем корневую директорию в path
sys.path.insert(0, str(Path(__file__).parent))

from src.infrastructure.audio.audio_bridge_websocket import AudioBridgeWebSocket
from src.core.config import get_settings, AudioConfig, ElevenLabsConfig
import structlog

# Настройка логирования
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.dev.ConsoleRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# Глобальная переменная для доступа к bridge извне
global_bridge = None


class AudioBridgeDaemon:
    """Демон для постоянной работы аудио моста"""
    
    def __init__(self):
        self.bridge = None
        self.running = False
        self.start_time = None
        
    async def start(self):
        """Запуск демона"""
        print("\n" + "="*50)
        print("🎵 Voice AI Audio Bridge")
        print("="*50)
        
        # Загрузка конфигурации
        settings = get_settings()
        
        # Проверка конфигурации
        if not settings.elevenlabs_api_key:
            print("❌ ELEVENLABS_API_KEY not set in .env!")
            sys.exit(1)
            
        if not settings.elevenlabs_agent_id:
            print("❌ ELEVENLABS_AGENT_ID not set in .env!")
            sys.exit(1)
        
        print(f"📋 Configuration:")
        print(f"   ElevenLabs Agent: {settings.elevenlabs_agent_id[:8]}...")
        print(f"   Sample Rate: 8kHz (telephony) → 16kHz (AI)")
        print(f"   Chunk Size: 20ms")
        print()
        
        # Создание конфигураций
        audio_config = AudioConfig(
            in_device=settings.audio_in_device,
            out_device=settings.audio_out_device,
            sample_rate_telephony=8000,
            sample_rate_ai=16000,
            chunk_size_ms=20
        )
        
        elevenlabs_config = ElevenLabsConfig(
            api_key=settings.elevenlabs_api_key,
            agent_id=settings.elevenlabs_agent_id,
            ws_url=settings.elevenlabs_ws_url
        )
        
        # Конфигурация прокси
        proxy_config = None
        if settings.use_proxy:
            proxy_config = {
                'use_proxy': True,
                'proxy_type': settings.proxy_type,
                'proxy_host': settings.proxy_host,
                'proxy_port': settings.proxy_port,
                'proxy_user': settings.proxy_user,
                'proxy_pass': settings.proxy_pass
            }
            print(f"🌐 Using {settings.proxy_type.upper()} proxy: {settings.proxy_host}:{settings.proxy_port}")
        
        # Создание и запуск моста
        self.bridge = AudioBridgeWebSocket(audio_config, elevenlabs_config, proxy_config=proxy_config)
        
        # Сохраняем в глобальную переменную для доступа извне
        global global_bridge
        global_bridge = self.bridge
        
        try:
            print("🔌 Connecting to audio pipes...")
            # Запускаем транспорт
            await self.bridge.start_transport_only()
            print("✅ Audio pipes connected")
            
            print("⏸️  WebSocket NOT connected yet - waiting for call signal")
            print("   Will connect only when someone answers the phone!")
            
            # Запускаем мониторинг файла-сигнала для подключения WebSocket
            asyncio.create_task(self._monitor_websocket_signal())
            
            self.running = True
            self.start_time = datetime.now()
            
            print("\n✅ Audio bridge is running!")
            print("👂 Listening for audio... (Ctrl+C to stop)")
            print("-"*50)
            
            # Мониторинг статуса
            await self.monitor_status()
            
        except Exception as e:
            logger.error(f"Failed to start bridge: {e}")
            await self.stop()
            sys.exit(1)
    
    async def _monitor_websocket_signal(self):
        """Мониторинг сигнала для подключения/отключения WebSocket"""
        import os
        websocket_connected = False
        
        print("🔍 Starting WebSocket signal monitor...")
        print(f"   Checking for signals every 100ms")
        
        check_count = 0
        while self.running:
            try:
                check_count += 1
                if check_count % 50 == 0:  # Каждые 5 секунд
                    print(f"   [Monitor] Still checking... (WebSocket connected: {websocket_connected})")
                
                # Проверяем сигнал для подключения
                if not websocket_connected and os.path.exists("/tmp/connect_websocket"):
                    print("\n🎯 CALL ANSWERED! Connecting to ElevenLabs WebSocket...")
                    print(f"   Signal file found at: /tmp/connect_websocket")
                    await self.bridge.start_websocket()
                    print("✅ ElevenLabs WebSocket connected!")
                    websocket_connected = True
                    os.remove("/tmp/connect_websocket")
                    print("   Signal file removed")
                
                # Проверяем сигнал для отключения
                elif websocket_connected and os.path.exists("/tmp/disconnect_websocket"):
                    print("\n📵 CALL ENDED! Disconnecting ElevenLabs WebSocket...")
                    await self.bridge.elevenlabs.disconnect()
                    print("✅ ElevenLabs WebSocket disconnected, credits saved!")
                    websocket_connected = False
                    os.remove("/tmp/disconnect_websocket")
                    
                await asyncio.sleep(0.1)  # Проверка каждые 100мс для минимальной задержки
                
            except Exception as e:
                logger.error(f"WebSocket signal monitor error: {e}")
                await asyncio.sleep(1)
    
    async def monitor_status(self):
        """Мониторинг и вывод статуса"""
        status_counter = 0
        
        while self.running:
            try:
                await asyncio.sleep(5)  # Обновление каждые 5 секунд
                
                status_counter += 1
                
                # Каждые 30 секунд показываем полный статус
                if status_counter % 6 == 0:
                    uptime = datetime.now() - self.start_time
                    metrics = self.bridge.metrics
                    
                    print(f"\n📊 Status Update [{datetime.now().strftime('%H:%M:%S')}]")
                    print(f"   Uptime: {uptime}")
                    print(f"   Packets processed: {metrics.packets_from_caller + metrics.packets_from_ai}")
                    print(f"   Data transferred: {(metrics.bytes_from_caller + metrics.bytes_from_ai) / 1024:.1f} KB")
                    print(f"   Errors: {metrics.errors}")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Monitor error: {e}")
    
    async def stop(self):
        """Остановка демона"""
        print("\n⏹️  Stopping audio bridge...")
        self.running = False
        
        if self.bridge:
            await self.bridge.stop()
        
        print("✅ Audio bridge stopped")
    
    async def run(self):
        """Главный цикл"""
        await self.start()
        
        # Ждём сигнала остановки
        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await self.stop()


def signal_handler(sig, frame):
    """Обработчик сигналов"""
    print("\n📛 Received interrupt signal")
    # Устанавливаем флаг для корректной остановки
    if daemon.running:
        daemon.running = False


async def main():
    """Главная функция"""
    global daemon
    daemon = AudioBridgeDaemon()
    
    # Устанавливаем обработчик сигналов
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await daemon.run()
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)