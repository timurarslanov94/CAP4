#!/bin/bash

echo "🚀 Запуск полной системы Voice AI Agent"
echo "======================================="

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Функция для проверки процесса
check_process() {
    if pgrep -f "$1" > /dev/null; then
        echo -e "${GREEN}✅ $2 уже запущен${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️  $2 не запущен${NC}"
        return 1
    fi
}

# 1. Проверка .env файла
echo -e "${BLUE}1. Проверка конфигурации${NC}"
if [ ! -f .env ]; then
    echo -e "${RED}❌ .env файл не найден!${NC}"
    echo "   Создайте .env файл с переменными окружения"
    exit 1
fi

source .env

if [ -z "$ELEVENLABS_API_KEY" ]; then
    echo -e "${RED}❌ ELEVENLABS_API_KEY не установлен в .env!${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Конфигурация проверена${NC}"

# 2. Создание pipes если не существуют
echo -e "\n${BLUE}2. Проверка audio pipes${NC}"
PIPE_IN="/tmp/baresip_audio_in.pcm"
PIPE_OUT="/tmp/baresip_audio_out.pcm"

if [ ! -p "$PIPE_IN" ] || [ ! -p "$PIPE_OUT" ]; then
    echo "📝 Создание audio pipes..."
    ./setup_audio_pipes.sh
else
    echo -e "${GREEN}✅ Audio pipes существуют${NC}"
fi

# 3. Очистка старых сигнальных файлов
echo -e "\n${BLUE}3. Очистка старых сигналов${NC}"
rm -f /tmp/connect_websocket /tmp/disconnect_websocket
echo -e "${GREEN}✅ Сигнальные файлы очищены${NC}"

# 4. Запуск Baresip
echo -e "\n${BLUE}4. Запуск Baresip${NC}"
if check_process "baresip" "Baresip"; then
    echo "   Перезапуск не требуется"
else
    echo "🔊 Запуск Baresip с конфигурацией aubridge..."
    # Запускаем Baresip в фоне
    baresip -f config/baresip > logs/baresip.log 2>&1 &
    BARESIP_PID=$!
    
    # Ждём пока Baresip запустится
    sleep 3
    
    if kill -0 $BARESIP_PID 2>/dev/null; then
        echo -e "${GREEN}✅ Baresip запущен (PID: $BARESIP_PID)${NC}"
    else
        echo -e "${RED}❌ Не удалось запустить Baresip${NC}"
        echo "   Проверьте logs/baresip.log"
        exit 1
    fi
fi

# 5. Запуск Audio Bridge
echo -e "\n${BLUE}5. Запуск Audio Bridge${NC}"
if check_process "run_audio_bridge.py" "Audio Bridge"; then
    echo "   Перезапуск не требуется"
else
    echo "🌉 Запуск Audio Bridge..."
    # Запускаем Audio Bridge в фоне
    python run_audio_bridge.py > logs/audio_bridge.log 2>&1 &
    BRIDGE_PID=$!
    
    sleep 2
    
    if kill -0 $BRIDGE_PID 2>/dev/null; then
        echo -e "${GREEN}✅ Audio Bridge запущен (PID: $BRIDGE_PID)${NC}"
    else
        echo -e "${RED}❌ Не удалось запустить Audio Bridge${NC}"
        echo "   Проверьте logs/audio_bridge.log"
        exit 1
    fi
fi

# 6. Запуск API сервера (если не запущен)
echo -e "\n${BLUE}6. Проверка API сервера${NC}"
if check_process "uvicorn src.main:app" "API сервер"; then
    echo -e "${YELLOW}ℹ️  API сервер должен быть запущен отдельно через 'make run-dev'${NC}"
else
    echo -e "${YELLOW}⚠️  API сервер не запущен${NC}"
    echo -e "${YELLOW}   Запустите его в отдельном терминале: make run-dev${NC}"
fi

# 7. Итоговый статус
echo -e "\n${BLUE}========================================${NC}"
echo -e "${GREEN}✅ Система готова к работе!${NC}"
echo ""
echo "📊 Логи:"
echo "   - Baresip:      logs/baresip.log"
echo "   - Audio Bridge: logs/audio_bridge.log"
echo "   - API сервер:   в терминале с 'make run-dev'"
echo ""
echo "📡 Архитектура:"
echo "   1. Baresip обрабатывает SIP/RTP через aubridge → pipes"
echo "   2. Audio Bridge читает из pipes и управляет WebSocket"
echo "   3. API сервер создаёт сигналы для управления WebSocket"
echo ""
echo "🔍 Мониторинг:"
echo "   - tail -f logs/audio_bridge.log    # Audio Bridge логи"
echo "   - tail -f logs/baresip.log        # Baresip логи"
echo ""
echo "⏹️  Остановка системы:"
echo "   ./stop_all.sh"
echo ""