# 🎯 Запуск Voice AI Agent с WebSocket интеграцией

## ⚡ Быстрый старт (3 команды)

```bash
# Терминал 1: Запуск моста
./start_ai_bridge.sh

# Терминал 2: Запуск Baresip
./start_baresip.sh

# Терминал 3: Запуск API сервера
make run
```

## 📋 Пошаговая инструкция

### 1️⃣ Подготовка окружения

```bash
# Установка зависимостей (один раз)
make init

# Проверка .env файла
cat .env | grep ELEVENLABS
# Должны быть заполнены:
# ELEVENLABS_API_KEY=...
# ELEVENLABS_AGENT_ID=...
```

### 2️⃣ Настройка аудио pipes (ВАЖНО: делать ДО запуска Baresip!)

```bash
# Создание named pipes
./setup_audio_pipes.sh

# Проверка что pipes созданы
ls -la /tmp/baresip_audio_*.pcm
# Должны увидеть:
# prw-rw-rw-  /tmp/baresip_audio_in.pcm
# prw-rw-rw-  /tmp/baresip_audio_out.pcm
```

### 3️⃣ Запуск аудио моста (ПЕРВЫМ!)

```bash
# В отдельном терминале - мост должен работать постоянно
python run_audio_bridge.py

# Вы увидите:
# ✅ Audio pipes connected
# 🌐 Connected to ElevenLabs WebSocket
# 👂 Listening for audio... (Ctrl+C to stop)
```

### 4️⃣ Запуск Baresip с pipe конфигурацией

```bash
# В новом терминале
./start_baresip_with_pipes.sh

# Или вручную:
baresip -f ~/.baresip_pipes

# Проверка регистрации:
# В консоли baresip введите: r
# Должны увидеть: 883140776920289@sip.exolve.ru [OK]
```

### 5️⃣ Запуск FastAPI сервера

```bash
# В третьем терминале
make run

# Сервер запустится на http://localhost:8000
```

### 6️⃣ Тестовый звонок

```bash
# Инициировать звонок через API
curl -X POST http://localhost:8000/api/calls/start \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+79273280718"}'

# Или через веб-интерфейс:
open http://localhost:8000/docs
```

## 🔍 Мониторинг и отладка

### Проверка работы pipes:
```bash
# Смотреть поток данных от Baresip
xxd /tmp/baresip_audio_out.pcm | head

# Проверить что мост читает данные
tail -f logs/audio_bridge.log
```

### Проверка WebSocket соединения:
```bash
# Логи моста покажут:
# [INFO] WebSocket: Sending audio chunk (640 bytes)
# [INFO] WebSocket: Received AI response (320 bytes)
```

### Метрики моста (каждые 10 сек):
```
Audio bridge metrics:
  caller_to_ai: {packets: 500, bytes: 160000}
  ai_to_caller: {packets: 450, bytes: 144000}
  resampling_ops: 950
  errors: 0
```

## ⚠️ Важные моменты

1. **Порядок запуска критичен:**
   - Сначала аудио мост (читатель pipes)
   - Потом Baresip (писатель pipes)
   - Потом API сервер

2. **Не останавливайте мост во время звонка** - Baresip зависнет!

3. **При ошибке "Broken pipe":**
   ```bash
   # Перезапустить всё в правильном порядке
   killall baresip
   pkill -f run_audio_bridge
   ./setup_audio_pipes.sh  # Пересоздать pipes
   # И начать с шага 3
   ```

## 🛑 Остановка системы

```bash
# Правильный порядок остановки:
1. Ctrl+C в терминале с API сервером
2. В baresip: /quit
3. Ctrl+C в терминале с мостом

# Или всё сразу:
./stop_all.sh
```

## 📊 Архитектура потока данных

```
┌─────────────┐     8kHz PCM      ┌──────────────┐
│   Caller    │ ◄──────────────► │   Baresip    │
│  (телефон)  │                   │  (SIP/RTP)   │
└─────────────┘                   └──────────────┘
                                          │
                                          │ pipes
                                          ▼
                                  ┌──────────────┐
                                  │ Audio Bridge │
                                  │   (Python)   │
                                  └──────────────┘
                                          │
                                    resample 8→16kHz
                                          │
                                          ▼
                                  ┌──────────────┐
                                  │  WebSocket   │
                                  └──────────────┘
                                          │
                                          ▼
                                  ┌──────────────┐
                                  │  ElevenLabs  │
                                  │   AI Agent   │
                                  └──────────────┘
```

## 🐛 Troubleshooting

| Проблема | Решение |
|----------|---------|
| "FIFO: No such file" | Запустить `./setup_audio_pipes.sh` |
| "Baresip hangs on call" | Убедиться что мост запущен |
| "No audio in call" | Проверить конфигурацию pipes в baresip |
| "WebSocket connection failed" | Проверить ELEVENLABS_API_KEY в .env |
| "High latency" | Уменьшить chunk_size_ms в конфигурации |

## 📝 Конфигурация

Все настройки в `.env` файле:
```bash
# Audio settings
AUDIO_CHUNK_SIZE_MS=20  # Размер аудио чанка (мс)

# ElevenLabs
ELEVENLABS_API_KEY=your_key_here
ELEVENLABS_AGENT_ID=your_agent_id
```

---

💡 **Совет:** Используйте `tmux` или `screen` для управления терминалами:
```bash
tmux new-session -s voiceai
# Ctrl+B, C - новое окно
# Ctrl+B, 0-2 - переключение между окнами
```