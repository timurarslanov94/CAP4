#!/bin/bash

echo "🔄 Restarting Audio Bridge with latest code..."

# Очищаем старые логи
echo "📝 Clearing old logs..."
> logs/audio_bridge.log

# Очищаем старые сигналы
rm -f /tmp/connect_websocket /tmp/disconnect_websocket

echo "✅ Ready to start with fresh logs"
echo ""
echo "Starting Audio Bridge..."
./start_ai_bridge.sh