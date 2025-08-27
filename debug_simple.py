#!/usr/bin/env python3
"""
Простая отладка: получаем аудио от ElevenLabs и сразу пишем в файл.
Без всяких очередей и сложностей.
"""

import asyncio
import sys
from pathlib import Path
import os

# Добавляем корневую директорию в path
sys.path.insert(0, str(Path(__file__).parent))

from src.infrastructure.ai.elevenlabs_client import ElevenLabsClient
from src.core.config import get_settings


async def main():
    print("=" * 50)
    print("🔍 DEBUG: ElevenLabs -> File Direct Write")
    print("=" * 50)
    
    # Загружаем настройки
    settings = get_settings()
    
    config = {
        'api_key': settings.elevenlabs_api_key,
        'agent_id': settings.elevenlabs_agent_id,
        'ws_url': settings.elevenlabs_ws_url
    }
    
    # Прокси конфигурация
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
    
    client = ElevenLabsClient(config, proxy_config)
    
    # Открываем файл для записи аудио
    audio_file = open("debug_audio.pcm", "wb")
    
    # Также пробуем открыть pipe (если Baresip запущен)
    pipe_fd = None
    try:
        pipe_path = "/tmp/baresip_audio_in.pcm"
        if os.path.exists(pipe_path):
            # Используем O_RDWR на macOS чтобы избежать блокировки
            pipe_fd = os.open(pipe_path, os.O_RDWR | os.O_NONBLOCK)
            print(f"✅ Opened pipe: {pipe_path}")
        else:
            print(f"⚠️  Pipe not found: {pipe_path}")
    except Exception as e:
        print(f"❌ Cannot open pipe: {e}")
    
    try:
        # Подключаемся
        print("\n🔌 Connecting to ElevenLabs...")
        await client.connect()
        print("✅ Connected!")
        
        # Слушаем аудио
        print("\n📡 Listening for audio (30 seconds)...")
        print("   Audio will be saved to: debug_audio.pcm")
        if pipe_fd:
            print("   Also writing to pipe for Baresip")
        
        chunks = 0
        total_bytes = 0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < 30:
            try:
                audio = await asyncio.wait_for(
                    client.receive_audio(),
                    timeout=0.5
                )
                
                if audio:
                    chunks += 1
                    total_bytes += len(audio)
                    
                    # Сохраняем в файл
                    audio_file.write(audio)
                    audio_file.flush()
                    
                    # Пробуем записать в pipe
                    if pipe_fd:
                        try:
                            # Для pipe нужно писать чанками по 320 байт (8kHz)
                            # Но у нас аудио в другом формате, поэтому пишем как есть
                            os.write(pipe_fd, audio[:320] if len(audio) >= 320 else audio)
                        except:
                            pass  # Игнорируем ошибки pipe
                    
                    if chunks == 1:
                        print(f"🎵 First chunk! Size: {len(audio)} bytes")
                        print(f"   Format: {client.output_format}")
                    elif chunks % 10 == 0:
                        print(f"   Chunk {chunks}: Total {total_bytes} bytes")
                    
            except asyncio.TimeoutError:
                continue
        
        print(f"\n📊 Results:")
        print(f"   Chunks received: {chunks}")
        print(f"   Total bytes: {total_bytes}")
        print(f"   Audio saved to: debug_audio.pcm")
        
        if chunks > 0:
            print("\n✅ SUCCESS! Audio received and saved.")
            print("\nTo play the audio:")
            print("   ffplay -f s16le -ar 16000 -ac 1 debug_audio.pcm")
        else:
            print("\n⚠️ No audio received!")
        
    finally:
        await client.disconnect()
        audio_file.close()
        if pipe_fd:
            os.close(pipe_fd)
        print("\n✅ Done")


if __name__ == "__main__":
    asyncio.run(main())