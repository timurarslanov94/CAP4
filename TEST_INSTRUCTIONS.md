# Инструкция по тестированию системы

## Что было исправлено

1. ✅ **Убран избыточный HTTP polling** - SIPCallMonitor больше не опрашивает `/api/calls` каждые 2 секунды
2. ✅ **События мониторятся напрямую через TCP** - CallService читает события от Baresip в реальном времени
3. ✅ **WebSocket подключается только при SIP 200 OK** - экономия кредитов ElevenLabs

## Как протестировать

### 1. Перезапустите API сервер

```bash
# Остановите сервер (Ctrl+C) и запустите заново
python main.py
```

**Что проверить:**
- ❌ НЕ должно быть сообщений о запуске SIPCallMonitor
- ✅ Должно быть: "API started - SIP events monitored directly via Baresip TCP"
- ❌ НЕ должно быть постоянных логов "GET /api/calls"

### 2. Тест детекции SIP событий

```bash
python test_sip_events.py 79123456789
```

**Что должно произойти:**
- При ответе человека: вы увидите "🎉 CALL_ESTABLISHED (SIP 200 OK)"
- При сообщении оператора: вы увидите "📢 CALL_PROGRESS (SIP 183)"

### 3. Полный тест звонка через API

```bash
# Сделайте звонок
curl -X POST http://localhost:8000/api/calls/dial \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "79123456789"}'
```

**Проверьте логи в терминале с API:**
```
📡 Starting real-time monitoring for call <UUID>
⏳ Waiting for SIP events from Baresip...
   - SIP 183 (CALL_PROGRESS) = operator message → NO WebSocket
   - SIP 200 (CALL_ESTABLISHED) = real answer → CONNECT WebSocket
```

**Проверьте логи в терминале с Audio Bridge:**
- При SIP 183: ничего не должно происходить
- При SIP 200: должно появиться "🎯 CALL ANSWERED! Connecting to ElevenLabs WebSocket..."

### 4. Проверка экономии кредитов

**Сценарий 1: Звонок на автоответчик/оператора**
1. Позвоните на номер с автоответчиком
2. Проверьте логи - должен быть только CALL_PROGRESS (SIP 183)
3. WebSocket НЕ должен подключаться
4. Кредиты ElevenLabs НЕ должны списываться

**Сценарий 2: Звонок с реальным ответом**
1. Позвоните на номер где ответит человек
2. Проверьте логи - должен быть CALL_ESTABLISHED (SIP 200)
3. WebSocket должен подключиться СРАЗУ после ответа
4. При завершении звонка WebSocket должен отключиться

### 5. Мониторинг производительности

```bash
# Проверьте, что нет избыточных HTTP запросов
tail -f main.log | grep "GET /api/calls"
```

Если всё работает правильно, вы НЕ должны видеть постоянных запросов к этому endpoint.

## Чек-лист успешного теста

- [ ] API сервер запускается без SIPCallMonitor
- [ ] Нет постоянных GET запросов к /api/calls
- [ ] SIP 183 (оператор) НЕ вызывает подключение WebSocket
- [ ] SIP 200 (реальный ответ) СРАЗУ подключает WebSocket
- [ ] WebSocket отключается при завершении звонка
- [ ] Кредиты ElevenLabs не тратятся на автоответчики

## Если что-то не работает

1. **WebSocket не подключается при ответе:**
   - Проверьте, что Audio Bridge запущен (`python run_audio_bridge.py`)
   - Проверьте файл `/tmp/connect_websocket` - он должен создаваться при SIP 200

2. **Всё равно идут запросы к /api/calls:**
   - Убедитесь, что изменения в `src/api/app.py` сохранены
   - Перезапустите API сервер
   - Проверьте, что никакие другие скрипты не запущены

3. **События от Baresip не приходят:**
   - Проверьте, что Baresip запущен с правильными настройками
   - Проверьте порт 4444 - `telnet localhost 4444`
   - Проверьте логи Baresip в терминале