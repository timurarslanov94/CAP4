#!/bin/bash

echo "🚀 Starting Complete Voice System"
echo "=================================="

# 1. Сначала запускаем Baresip
echo ""
echo "1️⃣ Starting Baresip..."
./start_baresip_with_aubridge.sh &
BARESIP_PID=$!
echo "   Baresip PID: $BARESIP_PID"

# Ждём пока Baresip запустится
echo "   Waiting for Baresip to start..."
sleep 3

# Проверяем что Baresip запустился
if ! ps -p $BARESIP_PID > /dev/null; then
    echo "❌ Baresip failed to start!"
    exit 1
fi

echo "✅ Baresip is running"

# 2. Теперь запускаем Audio Bridge
echo ""
echo "2️⃣ Starting Audio Bridge..."
python3 run_audio_bridge.py 2>&1 | tee logs/audio_bridge.log &
BRIDGE_PID=$!
echo "   Audio Bridge PID: $BRIDGE_PID"

# 3. Показываем статус
echo ""
echo "✅ System Started Successfully!"
echo "=================================="
echo "📞 Baresip PID: $BARESIP_PID"
echo "🌉 Bridge PID: $BRIDGE_PID"
echo ""
echo "📊 Logs:"
echo "   Audio Bridge: logs/audio_bridge.log"
echo ""
echo "⏹️  Press Ctrl+C to stop all services"

# Ждём прерывания
trap "echo ''; echo 'Stopping services...'; kill $BARESIP_PID $BRIDGE_PID 2>/dev/null; exit" INT TERM

# Держим скрипт запущенным
while true; do
    sleep 1
done