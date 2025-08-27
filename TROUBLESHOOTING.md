# Troubleshooting Guide

## Problem: "could not find UA for [number]"

### Причина
Baresip интерпретирует параметр команды `dial` как UA идентификатор, а не номер телефона.

### Решение
Метод `dial()` теперь автоматически пробует несколько форматов:

1. **SIP URI**: `sip:79123456789@sip.exolve.ru` - стандартный формат
2. **Простой номер**: `79123456789` - если первый не работает  
3. **С индексом UA**: `0 sip:79123456789@sip.exolve.ru` - для старых версий

### Проверка
Используйте тестовый скрипт:
```bash
python test_baresip_dial.py 79123456789
```

### Дополнительная диагностика

1. **Проверьте регистрацию SIP:**
```bash
# В консоли Baresip нажмите 'r' для просмотра регистраций
```

2. **Проверьте список UA:**
```bash
# В консоли Baresip нажмите 'u' для списка User Agents
```

3. **Проверьте формат в accounts файле:**
```bash
cat config/baresip/accounts
```
Должно быть:
```
<sip:user@domain>;auth_user=user;auth_pass=pass;outbound="sip:server"
```

## Problem: Постоянные GET запросы к /api/calls

### Причина
SIPCallMonitor создавал HTTP polling loop, опрашивая API каждые 2 секунды.

### Решение
✅ Отключен SIPCallMonitor в `src/api/app.py`
✅ События мониторятся напрямую через Baresip TCP

### Проверка
В логах API не должно быть постоянных:
```
INFO: 127.0.0.1:xxxxx - "GET /api/calls HTTP/1.1" 200 OK
```

## Problem: WebSocket подключается при автоответчике

### Причина
Система не различала SIP 183 (оператор) и SIP 200 (реальный ответ).

### Решение
✅ Мониторинг SIP событий в `CallService._monitor_call_events()`
✅ WebSocket подключается только при `CALL_ESTABLISHED` (SIP 200)
✅ При `CALL_PROGRESS` (SIP 183) WebSocket НЕ подключается

### Проверка
При звонке на автоответчик в логах должно быть:
```
📢 CALL_PROGRESS (SIP 183) detected
❌ NOT connecting WebSocket (saving ElevenLabs credits)
```

## Common Baresip Commands

### Через TCP интерфейс (netstring format):
```python
# Dial
{"command": "dial", "params": "sip:number@domain"}

# Hangup
{"command": "hangup"}

# Answer incoming call
{"command": "accept"}

# Get registration info
{"command": "reginfo"}
```

### В консоли Baresip:
- `d` - dial (набрать номер)
- `h` - hangup (повесить трубку)
- `a` - answer (ответить)
- `r` - registration info
- `u` - user agents list
- `?` - help