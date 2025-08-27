#!/bin/bash

echo "🛑 Stopping Voice AI System"
echo "=========================="

# Остановка API сервера
echo "Stopping API server..."
pkill -f "uvicorn src.main:app"

# Остановка Baresip
echo "Stopping Baresip..."
killall baresip 2>/dev/null

# Остановка аудио моста
echo "Stopping audio bridge..."
pkill -f "run_audio_bridge.py"

# Очистка pipes (опционально)
read -p "Remove audio pipes? (y/n) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -f /tmp/baresip_audio_in.pcm
    rm -f /tmp/baresip_audio_out.pcm
    echo "✅ Pipes removed"
fi

echo "✅ All services stopped"