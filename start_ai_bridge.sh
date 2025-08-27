#!/bin/bash

echo "🚀 Starting Voice AI Bridge"
echo "=========================="

# Проверка переменных окружения
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    exit 1
fi

source .env

if [ -z "$ELEVENLABS_API_KEY" ]; then
    echo "❌ ELEVENLABS_API_KEY not set in .env!"
    exit 1
fi

# Создание pipes если не существуют
PIPE_IN="/tmp/baresip_audio_in.pcm"
PIPE_OUT="/tmp/baresip_audio_out.pcm"

if [ ! -p "$PIPE_IN" ] || [ ! -p "$PIPE_OUT" ]; then
    echo "📝 Creating audio pipes..."
    ./setup_audio_pipes.sh
fi

# Создание директории для логов
mkdir -p logs

# Запуск моста
echo "🌉 Starting audio bridge..."
echo "   Input pipe:  $PIPE_OUT (from Baresip)"
echo "   Output pipe: $PIPE_IN (to Baresip)"
echo ""
echo "📊 Logs: logs/audio_bridge.log"
echo "⏹️  Press Ctrl+C to stop"
echo ""

# Активируем виртуальное окружение если есть
if [ -f .venv/bin/activate ]; then
    source .venv/bin/activate
fi

# Запуск Python моста с логированием
python run_audio_bridge.py 2>&1 | tee logs/audio_bridge.log