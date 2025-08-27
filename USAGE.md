# Voice AI System - Руководство по использованию

## ✅ Система работает корректно!

### Что было исправлено:
1. ✅ Команда dial теперь использует правильный формат: `sip:number@domain`
2. ✅ Убран избыточный HTTP polling (SIPCallMonitor отключён)
3. ✅ WebSocket подключается ТОЛЬКО при реальном ответе (SIP 200)
4. ✅ WebSocket отключается при завершении звонка

## Запуск системы

### Terminal 1 - Audio Bridge
```bash
python run_audio_bridge.py
# или
./start_ai_bridge.sh
```

### Terminal 2 - Baresip
```bash
baresip -f config/baresip
# или
./start_baresip.sh
```

### Terminal 3 - API Server
```bash
python main.py
```

## Совершение звонка

### Через API:
```bash
curl -X POST http://localhost:8000/api/calls/start \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+79123456789"}'
```

### Через веб-интерфейс:
Откройте http://localhost:8000/docs

## Как работает система

### 1. При звонке на автоответчик (SIP 183):
```
📢 CALL_PROGRESS - SIP 183 Session Progress
   → This is operator/voicemail message
   → WebSocket should NOT be connected
```
**Результат:** WebSocket НЕ подключается, кредиты ElevenLabs сохранены ✅

### 2. При ответе реального человека (SIP 200):
```
🎉 CALL_ESTABLISHED - SIP 200 OK!
   → Real person answered the phone
   → WebSocket should be connected NOW
```
**Результат:** WebSocket подключается СРАЗУ ✅

### 3. При завершении звонка:
```
📵 Call ended: CALL_CLOSED
   → WebSocket should be disconnected
```
**Результат:** WebSocket отключается, экономия кредитов ✅

## Проверка работы

### 1. Убедитесь, что нет лишних HTTP запросов:
В логах API НЕ должно быть постоянных:
```
INFO: 127.0.0.1:xxxxx - "GET /api/calls HTTP/1.1" 200 OK
```

### 2. Проверьте детекцию SIP событий:
```bash
python test_sip_events.py 79123456789
```

### 3. Проверьте формат команды dial:
```bash
python test_baresip_dial.py 79123456789
```

## Важные файлы конфигурации

### `.env` - основные настройки:
```env
# ElevenLabs
ELEVENLABS_API_KEY=your_key
ELEVENLABS_AGENT_ID=your_agent_id

# Exolve
EXOLVE_SIP_USER=883140776920289
EXOLVE_SIP_PASS=your_password
EXOLVE_SIP_DOMAIN=sip.exolve.ru
```

### `config/baresip/accounts` - SIP аккаунт:
```
<sip:883140776920289@sip.exolve.ru>;auth_user=883140776920289;auth_pass=pass;outbound="sip:80.75.130.100"
```

### `config/baresip/config` - настройки Baresip:
```
ctrl_tcp_listen         0.0.0.0:4444
module                  ctrl_tcp.so
```

## Решение проблем

### Если звонок не проходит:
1. Проверьте регистрацию SIP в консоли Baresip (нажмите 'r')
2. Убедитесь, что используется правильный домен в .env
3. Запустите `python test_baresip_dial.py` для диагностики

### Если WebSocket не подключается:
1. Проверьте, что Audio Bridge запущен
2. Очистите старые сигнальные файлы:
   ```bash
   rm -f /tmp/connect_websocket /tmp/disconnect_websocket
   ```
3. Проверьте логи Audio Bridge

### Если есть постоянные GET запросы:
1. Перезапустите API сервер
2. Убедитесь, что в `src/api/app.py` отключён SIPCallMonitor

## Мониторинг

### Логи API сервера:
```bash
tail -f logs/api.log
```

### Логи Audio Bridge:
```bash
tail -f logs/audio_bridge.log
```

### События Baresip:
Смотрите в консоли Baresip или используйте `test_sip_events.py`

## Экономия кредитов ElevenLabs

Система автоматически:
- ❌ НЕ подключает WebSocket при автоответчиках (SIP 183)
- ✅ Подключает WebSocket только при реальном ответе (SIP 200)
- 📵 Отключает WebSocket сразу после завершения звонка

Это позволяет избежать трат на:
- Голосовые меню операторов
- Сообщения "абонент недоступен"
- Автоответчики и voicemail