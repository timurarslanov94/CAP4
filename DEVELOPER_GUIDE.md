# CAP4 - Руководство разработчика

## 📋 Оглавление
1. [Обзор проекта](#обзор-проекта)
2. [Архитектура системы](#архитектура-системы)
3. [Основные компоненты](#основные-компоненты)
4. [Конфигурация](#конфигурация)
5. [Запуск системы](#запуск-системы)
6. [API Endpoints](#api-endpoints)
7. [Поток обработки звонка](#поток-обработки-звонка)
8. [Протоколы и форматы](#протоколы-и-форматы)
9. [Отладка и мониторинг](#отладка-и-мониторинг)
10. [Расширение функциональности](#расширение-функциональности)

---

## 🎯 Обзор проекта

**CAP4** - это система интеграции SIP телефонии с AI голосовым ассистентом. Проект позволяет:
- Совершать исходящие звонки через SIP протокол
- Автоматически определять, ответил ли реальный человек или автоответчик
- Подключать AI ассистента (ElevenLabs) только при реальном ответе
- Обрабатывать аудиопотоки в реальном времени
- Экономить кредиты AI сервиса

### Ключевые технологии:
- **Python 3.13** - основной язык
- **FastAPI** - REST API и асинхронная обработка
- **Baresip** - SIP клиент для телефонии
- **ElevenLabs Conversational AI** - генерация и распознавание речи
- **WebSockets** - передача аудио в реальном времени
- **Dishka** - Dependency Injection контейнер
- **UV** - современный менеджер пакетов Python

---

## 🏗️ Архитектура системы

### Высокоуровневая схема:

```
┌─────────────┐     SIP/RTP      ┌──────────────┐     Audio      ┌─────────────────┐
│   Телефон   │ ◄──────────────► │   Baresip    │ ◄────────────► │  Audio Bridge   │
└─────────────┘                  └──────────────┘                 └─────────────────┘
                                         │                                │
                                    TCP Events                       WebSocket
                                         │                                │
                                         ▼                                ▼
                                  ┌──────────────┐                ┌─────────────────┐
                                  │ CallService  │                │  ElevenLabs AI  │
                                  └──────────────┘                └─────────────────┘
                                         │
                                    REST API
                                         │
                                         ▼
                                  ┌──────────────┐
                                  │   FastAPI    │
                                  └──────────────┘
```

### Слоевая архитектура:

```
├── API Layer (FastAPI endpoints)
│   └── src/api/
│       ├── app.py           # FastAPI приложение
│       └── routers/         # REST endpoints
│
├── Service Layer (бизнес-логика)
│   └── src/services/
│       ├── call_service.py  # Управление звонками
│       └── call_monitor.py  # Мониторинг событий
│
├── Infrastructure Layer
│   └── src/infrastructure/
│       ├── telephony/       # SIP интеграция
│       ├── audio/           # Аудио обработка
│       └── ai/              # AI интеграция
│
├── Domain Layer
│   └── src/models/          # Модели данных
│
└── Core
    └── src/core/
        ├── config.py        # Конфигурация
        └── di.py            # Dependency Injection
```

---

## 🔧 Основные компоненты

### 1. **CallService** (`src/services/call_service.py`)
**Назначение**: Центральный сервис управления звонками

**Основные функции**:
- `start_call()` - инициирует исходящий звонок
- `_monitor_call_events()` - мониторит SIP события в реальном времени
- `connect_elevenlabs()` - подключает AI при ответе человека
- `end_call()` - завершает звонок

**Ключевая логика**:
```python
# Определение типа ответа:
if event_type == 'CALL_ESTABLISHED':  # SIP 200 OK
    # Реальный человек - подключаем AI
    create_signal("/tmp/connect_websocket")
    
elif event_type == 'CALL_PROGRESS':  # SIP 183
    # Автоответчик - НЕ подключаем AI
    pass
```

### 2. **BaresipController** (`src/infrastructure/telephony/baresip_controller.py`)
**Назначение**: Управление SIP клиентом Baresip

**Протокол**: TCP на порту 4444, формат Netstring
**Основные команды**:
- `dial` - совершить звонок
- `hangup` - завершить звонок
- `accept` - принять входящий

**Формат Netstring**:
```
длина:{"command":"dial","params":"79123456789"},
```

### 3. **AudioBridge** (`src/infrastructure/audio/audio_bridge.py`)
**Назначение**: Мост между телефонией и AI

**Функции**:
- Захват аудио от Baresip (8kHz, µ-law)
- Конвертация форматов (8kHz ↔ 16kHz)
- Передача в ElevenLabs WebSocket
- Воспроизведение ответов AI

**Аудио устройства**:
- Input: `Baresip-RemoteAudio` (от телефона)
- Output: `Baresip-CallInput` (к телефону)

### 4. **ElevenLabsClient** (`src/infrastructure/ai/elevenlabs_client.py`)
**Назначение**: WebSocket клиент для AI сервиса

**Протокол**: WebSocket с JSON событиями
**Форматы аудио**:
- Input: PCM 16kHz
- Output: µ-law 8kHz

**События**:
- `conversation_initiation` - инициализация
- `audio` - аудиоданные
- `user_transcript` - распознанный текст пользователя
- `agent_response` - ответ AI

### 5. **Audio Bridge Process** (`run_audio_bridge.py`)
**Назначение**: Отдельный процесс для обработки аудио

**Особенности**:
- Работает независимо от основного API
- Мониторит сигнальные файлы
- Управляет WebSocket соединением

**Сигналы**:
- `/tmp/connect_websocket` - подключить AI
- `/tmp/disconnect_websocket` - отключить AI

---

## ⚙️ Конфигурация

### Переменные окружения (`.env`):

```bash
# Exolve SIP телефония
EXOLVE_API_KEY=<ваш_api_ключ>
EXOLVE_SIP_USER=<sip_логин>
EXOLVE_SIP_PASS=<sip_пароль>
EXOLVE_SIP_DOMAIN=sip.exolve.ru

# ElevenLabs AI
ELEVENLABS_API_KEY=<api_ключ>
ELEVENLABS_AGENT_ID=<id_агента>

# Baresip
BARESIP_HOST=localhost
BARESIP_CTRL_TCP_PORT=4444

# Приложение
APP_HOST=0.0.0.0
APP_PORT=8000
APP_DEBUG=false
APP_LOG_LEVEL=INFO
```

### Конфигурация Baresip (`config/baresip/config`):

```
# Основные модули
module          aubridge.so      # Аудио мост
module          ctrl_tcp.so      # TCP управление

# TCP контроль
ctrl_tcp_listen 0.0.0.0:4444

# Аудио кодеки
audio_codec     PCMU/8000/1     # G.711 µ-law
```

---

## 🚀 Запуск системы

### Требования:
- Python 3.13+
- Baresip с модулями aubridge и ctrl_tcp
- Виртуальные аудио устройства (BlackHole на macOS)

### Последовательность запуска:

#### Terminal 1 - Audio Bridge:
```bash
python run_audio_bridge.py
```
Запускает аудио мост и WebSocket менеджер.

#### Terminal 2 - Baresip:
```bash
baresip -f config/baresip
```
Запускает SIP клиент.

#### Terminal 3 - API Server:
```bash
python src/main.py
```
Запускает FastAPI сервер на порту 8000.

### Альтернативный запуск:
```bash
# Все компоненты одной командой
./start_full_system.sh
```

---

## 📡 API Endpoints

### POST `/api/calls/dial`
Инициирует исходящий звонок.

**Request:**
```json
{
  "phone_number": "79123456789"
}
```

**Response:**
```json
{
  "id": "uuid",
  "phone_number": "79123456789",
  "status": "dialing",
  "direction": "outbound",
  "started_at": "2024-01-20T10:00:00Z"
}
```

### GET `/api/calls/{call_id}`
Получает информацию о звонке.

### POST `/api/calls/{call_id}/hangup`
Завершает активный звонок.

### GET `/api/calls`
Список всех звонков.

---

## 📞 Поток обработки звонка

### 1. Инициация звонка:
```
Client → POST /api/calls/dial
  → CallService.start_call()
    → BaresipController.dial()
      → Baresip совершает SIP INVITE
```

### 2. Мониторинг событий:
```
CallService._monitor_call_events()
  → BaresipController.monitor_call_events()
    → TCP поток событий от Baresip
      → Callback обработка в реальном времени
```

### 3. Определение типа ответа:

#### Автоответчик (SIP 183):
```
CALL_PROGRESS → 
  Логирование "Operator message" →
    WebSocket НЕ подключается
```

#### Реальный человек (SIP 200):
```
CALL_ESTABLISHED → 
  create("/tmp/connect_websocket") →
    AudioBridge видит сигнал →
      ElevenLabsClient.connect() →
        WebSocket активен
```

### 4. Обработка аудио:
```
Телефон → Baresip → 
  Baresip-RemoteAudio (виртуальное устройство) →
    AudioBridge.capture() →
      Конвертация 8kHz → 16kHz →
        WebSocket → ElevenLabs

ElevenLabs → WebSocket →
  AudioBridge.receive() →
    Конвертация 16kHz → 8kHz →
      Baresip-CallInput →
        Baresip → Телефон
```

### 5. Завершение:
```
CALL_CLOSED event →
  create("/tmp/disconnect_websocket") →
    WebSocket отключается →
      Освобождение ресурсов
```

---

## 🔌 Протоколы и форматы

### Baresip TCP Protocol (Netstring):
```python
# Формат: длина:данные,
def encode_netstring(data: dict) -> bytes:
    json_str = json.dumps(data)
    json_bytes = json_str.encode('utf-8')
    length = len(json_bytes)
    return f"{length}:{json_str},".encode('utf-8')

# Пример команды:
{"command": "dial", "params": "79123456789"}
# Закодировано: 42:{"command":"dial","params":"79123456789"},
```

### ElevenLabs WebSocket Protocol:
```javascript
// Отправка аудио
{
  "type": "input_audio_buffer.append",
  "audio": "base64_encoded_pcm"
}

// Получение аудио
{
  "type": "audio",
  "audio": {
    "chunk": "base64_encoded_ulaw"
  }
}

// Транскрипция
{
  "type": "user_transcript",
  "transcript": "Привет, как дела?"
}
```

### SIP события от Baresip:
```python
# Ключевые события для логики:
CALL_OUTGOING    # Звонок инициирован
CALL_RINGING     # Телефон звонит
CALL_PROGRESS    # SIP 183 - автоответчик/оператор
CALL_ESTABLISHED # SIP 200 - реальный ответ
CALL_CLOSED      # Звонок завершён
```

---

## 🔍 Отладка и мониторинг

### Логирование:
```python
# Настройка в main.py
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer()  # Цветной вывод
    ]
)

# Использование:
logger = structlog.get_logger()
await logger.ainfo("Call started", call_id=call_id)
```

### Мониторинг Audio Bridge:
```bash
# Логи аудио моста
tail -f logs/audio_bridge.log

# Проверка сигналов
watch -n 1 'ls -la /tmp/*websocket*'
```

### Отладка Baresip:
```bash
# Интерактивная консоль Baresip
# Нажмите 'h' для справки
# 'd' - совершить звонок
# 'b' - завершить звонок
```

### Тестирование WebSocket:
```python
# debug_simple.py - простой тестовый клиент
python debug_simple.py
```

---

## 🔨 Расширение функциональности

### Добавление нового AI провайдера:

1. Создать клиент в `src/infrastructure/ai/`:
```python
class NewAIClient:
    async def connect(self) -> None: ...
    async def send_audio(self, frame: AudioFrame) -> None: ...
    async def disconnect(self) -> None: ...
```

2. Зарегистрировать в DI контейнере:
```python
# src/infrastructure/di/infrastructure_provider.py
@provide(scope=Scope.APP)
async def new_ai_client(config: Settings) -> NewAIClient:
    return NewAIClient(config)
```

3. Обновить CallService для использования нового клиента.

### Добавление входящих звонков:

1. Добавить endpoint в `src/api/routers/calls.py`:
```python
@router.post("/answer")
async def answer_call(call_service: FromDishka[CallService]):
    return await call_service.answer_incoming()
```

2. Реализовать логику в CallService:
```python
async def answer_incoming(self) -> Call:
    await self.baresip.send_command(BaresipCommand.ANSWER)
    # Логика обработки входящего
```

### Добавление записи звонков:

1. Создать сервис записи:
```python
class RecordingService:
    def start_recording(self, call_id: UUID): ...
    def stop_recording(self, call_id: UUID): ...
```

2. Интегрировать в AudioBridge:
```python
if self.recording_enabled:
    self.recording_service.write_frame(frame)
```

---

## 📚 Полезные ссылки

- [Baresip Documentation](https://github.com/baresip/baresip)
- [ElevenLabs API Docs](https://elevenlabs.io/docs/conversational-ai)
- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [Dishka DI Framework](https://github.com/reagento/dishka)

---

## ⚠️ Важные моменты

1. **Экономия кредитов**: WebSocket к ElevenLabs подключается ТОЛЬКО при SIP 200 (реальный ответ), игнорируя SIP 183 (автоответчики).

2. **Асинхронность**: Весь код асинхронный, используйте `async/await` везде.

3. **Разделение процессов**: Audio Bridge работает отдельным процессом для изоляции аудио обработки.

4. **Сигнальные файлы**: Межпроцессное взаимодействие через файлы `/tmp/*websocket`.

5. **Netstring протокол**: Все команды к Baresip должны быть в формате Netstring с корректным подсчётом байтов.

6. **Виртуальные устройства**: Требуются виртуальные аудио устройства (BlackHole на macOS, PulseAudio на Linux).

---

## 🤝 Контакты и поддержка

При возникновении вопросов обращайтесь к основному разработчику или создавайте issue в репозитории проекта.

---

*Документ обновлён: Январь 2025*