#!/bin/bash

echo "🎙️ Starting Baresip with aubridge (named pipes)"
echo "================================================"

# Проверка pipes
PIPE_IN="/tmp/baresip_audio_in.pcm"
PIPE_OUT="/tmp/baresip_audio_out.pcm"

if [ ! -p "$PIPE_IN" ] || [ ! -p "$PIPE_OUT" ]; then
    echo "📝 Creating audio pipes..."
    ./setup_audio_pipes.sh
fi

echo "✅ Audio pipes ready:"
echo "   Input:  $PIPE_IN"
echo "   Output: $PIPE_OUT"
echo ""

# ВАЖНО: Используем нашу конфигурацию с aubridge!
echo "🚀 Starting Baresip with config/baresip configuration..."
echo "   This config uses 'aubridge' module for named pipes"
echo ""

# Запуск Baresip с правильной конфигурацией
baresip -f config/baresip -v