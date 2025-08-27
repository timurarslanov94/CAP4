# Voice AI Agent - Решение проблемы со звуком

## Статус системы

### ✅ Что работает:
1. **WebSocket соединение с ElevenLabs** - успешно устанавливается
2. **Получение аудио от AI агента** - агент говорит, аудио приходит
3. **Запись аудио в pipe для Baresip** - аудио успешно передаётся в `/tmp/baresip_audio_in.pcm`
4. **Handshake протокол** - корректно обрабатывается

### ❌ Проблемы:
1. **Нет аудио от звонящего** - Baresip не передаёт входящее аудио в `/tmp/baresip_audio_out.pcm`
2. **Быстрое завершение звонка** - возможно из-за отсутствия аудио от пользователя

## Архитектура потоков данных

```
[Звонящий] <--SIP/RTP--> [Baresip] <--Named Pipes--> [Audio Bridge] <--WebSocket--> [ElevenLabs]
                             |                            |
                             v                            v
                    /tmp/baresip_audio_out.pcm   /tmp/baresip_audio_in.pcm
                    (от звонящего к AI)          (от AI к звонящему)
```

## Диагностика проблемы

В логах видно:
- `packets_from_caller: 0` - нет пакетов от звонящего
- `packets_from_ai: 2` - есть пакеты от AI
- `First chunk written to Baresip pipe: 320 bytes` - аудио записывается в pipe

## Решение

### 1. Проверка Baresip
Убедитесь, что Baresip правильно настроен для записи аудио:
```bash
# В консоли Baresip во время звонка:
/audio_debug
```

### 2. Проверка pipes
```bash
# Проверить, что pipes существуют и доступны:
ls -la /tmp/baresip_audio*.pcm

# Мониторинг данных в pipe:
hexdump -C /tmp/baresip_audio_out.pcm
```

### 3. Тестирование аудио потока
```bash
# Генерация тестового тона в pipe:
python3 test_direct_pipe.py

# Запись тестового аудио:
dd if=/dev/zero of=/tmp/baresip_audio_out.pcm bs=320 count=100
```

### 4. Конфигурация Baresip

Текущая конфигурация (config/baresip/config):
```
audio_player    aubridge,/tmp/baresip_audio_out.pcm   
audio_source    aubridge,/tmp/baresip_audio_in.pcm
```

Возможно, нужно добавить в config/baresip/modules.conf:
```
aubridge.so
```

### 5. Альтернативный подход

Если aubridge не работает, можно использовать модуль `aufile`:
```
audio_player    aufile,/tmp/baresip_audio_out.pcm
audio_source    aufile,/tmp/baresip_audio_in.pcm  
```

## Запуск системы

1. **Запустить Baresip:**
```bash
./start_baresip_with_aubridge.sh
```

2. **Запустить Audio Bridge:**
```bash
python3 run_audio_bridge.py
```

3. **Сделать звонок через Baresip:**
```
/dial sip:79273280718@sip.exolve.ru
```

4. **Создать сигнал для подключения WebSocket:**
```bash
touch /tmp/connect_websocket
```

## Мониторинг

Следите за логами:
```bash
tail -f logs/audio_bridge.log
```

Ключевые метрики:
- `packets_from_caller` - должно увеличиваться
- `packets_to_ai` - отправка аудио в ElevenLabs
- `packets_from_ai` - получение от агента
- `packets_to_caller` - передача в Baresip

## Дополнительная отладка

Если звук всё ещё не работает:

1. Проверьте права доступа к pipes
2. Убедитесь, что Baresip скомпилирован с поддержкой aubridge
3. Проверьте формат аудио (должен быть PCM 8kHz для телефонии)
4. Убедитесь, что прокси работает для WebSocket соединения