# Voice AI System Architecture

## Обзор системы

Система состоит из следующих компонентов:

```
[Phone] ←→ [Baresip SIP] ←→ [Audio Bridge] ←→ [ElevenLabs AI]
                ↓
          [TCP Events]
                ↓
         [CallService]
```

## Поток событий

### 1. Исходящий звонок
1. API получает запрос `POST /api/calls/dial`
2. CallService отправляет команду `dial` в Baresip через TCP
3. CallService запускает `_monitor_call_events()` для мониторинга SIP событий
4. Baresip инициирует SIP звонок

### 2. Обработка SIP событий

События от Baresip приходят через TCP в реальном времени:

- **CALL_OUTGOING** - звонок инициирован
- **CALL_RINGING** - телефон звонит  
- **CALL_PROGRESS (SIP 183)** - сообщение оператора/автоответчик
  - ❌ WebSocket НЕ подключается (экономия кредитов)
- **CALL_ESTABLISHED (SIP 200)** - реальный человек ответил
  - ✅ WebSocket подключается СРАЗУ
- **CALL_CLOSED** - звонок завершён
  - 🔌 WebSocket отключается

### 3. Управление WebSocket

WebSocket к ElevenLabs подключается ТОЛЬКО при реальном ответе человека:

```python
# В CallService._monitor_call_events():
if event_type == 'CALL_ESTABLISHED':  # SIP 200 OK
    # Создаём сигнал для подключения
    with open("/tmp/connect_websocket", "w") as f:
        f.write(str(call_id))
        
elif event_type == 'CALL_PROGRESS':  # SIP 183
    # НЕ подключаем WebSocket - это оператор
    pass
```

Audio Bridge мониторит сигнальные файлы:
- `/tmp/connect_websocket` - подключить WebSocket
- `/tmp/disconnect_websocket` - отключить WebSocket

## Правильная архитектура

### ✅ Что работает правильно:
1. **Прямой мониторинг через TCP** - CallService напрямую читает события от Baresip
2. **Разделение соединений** - отдельное TCP соединение для мониторинга событий
3. **Сигнальные файлы** - простая межпроцессная коммуникация
4. **Экономия кредитов** - WebSocket подключается только при реальном ответе

### ❌ Что было неправильно (исправлено):
1. ~~HTTP polling через SIPCallMonitor~~ - создавал циклическую зависимость
2. ~~Таймер 3 секунды для подключения~~ - не точно определял момент ответа
3. ~~Множество мониторов~~ - избыточная нагрузка

## Baresip TCP Protocol

### Netstring формат
```
длина:данные,
```
- `длина` - количество БАЙТОВ (не символов!)
- `данные` - JSON команда или событие
- `,` - завершающий символ

### Пример команды:
```python
cmd = {"command": "dial", "params": "79123456789"}
json_str = '{"command":"dial","params":"79123456789"}'
bytes = b'{"command":"dial","params":"79123456789"}'  # 42 байта
netstring = b'42:{"command":"dial","params":"79123456789"},'
```

### Пример события:
```
50:{"event":true,"type":"CALL_ESTABLISHED","param":""},
```

## Компоненты системы

### 1. BaresipController
- Управляет Baresip через TCP (порт 4444)
- Отправляет команды в netstring формате
- Мониторит события в отдельном TCP соединении

### 2. CallService  
- Бизнес-логика звонков
- Мониторит SIP события через `_monitor_call_events()`
- Управляет подключением WebSocket через сигнальные файлы

### 3. AudioBridge
- Мост между Baresip и ElevenLabs
- Работает как отдельный процесс (`run_audio_bridge.py`)
- Мониторит сигнальные файлы для управления WebSocket

### 4. ElevenLabsClient
- WebSocket соединение с ElevenLabs Conversational AI
- Подключается ТОЛЬКО при SIP 200 OK
- Отключается при завершении звонка

## Запуск системы

1. **Terminal 1 - Audio Bridge:**
```bash
python run_audio_bridge.py
```

2. **Terminal 2 - Baresip:**
```bash
baresip -f .baresip
```

3. **Terminal 3 - API Server:**
```bash
python main.py
```

## Важные моменты

1. **Экономия кредитов ElevenLabs:**
   - WebSocket подключается только при реальном ответе (SIP 200)
   - Игнорируются сообщения операторов (SIP 183)
   - WebSocket отключается сразу при завершении звонка

2. **Производительность:**
   - Нет HTTP polling - только прямые TCP события
   - События обрабатываются в реальном времени
   - Минимальная задержка между ответом и подключением AI

3. **Надёжность:**
   - Отдельные TCP соединения для команд и мониторинга
   - Таймауты на всех операциях
   - Корректная обработка ошибок и очистка ресурсов