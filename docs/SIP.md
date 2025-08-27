
# Exolve SIP API - Техническая документация для интеграции с ElevenLabs

## Обзор

Документация описывает техническую спецификацию работы с Exolve SIP API для создания исходящих звонков и интеграции с ElevenLabs Conversational AI. Покрывает протоколы SIP, SDP, RTP и обработку аудио.

## 1. Инфраструктура Exolve SIP

### 1.1. Сетевые параметры
- **SIP Домен**: `sip.exolve.ru`
- **SIP Сервер**: `80.75.130.100:5060` (UDP) ⭐ **Основной для SIP ID**
- **Дополнительные IP-адреса**:
  - `80.75.130.99:5060` — звонки с/на Static IP
  - `80.75.130.101:5060` — переадресация на SIP-соединение

### 1.2. Управление портами RTP

#### 1.2.1. Локальные RTP порты (ваша сторона)
- **Диапазон**: обычно 10000-20000 (конфигурируется)
- **Привязка**: bind к `0.0.0.0:random_port` или фиксированному порту
- **SDP**: указываете свой порт в `m=audio {ваш_rtp_port} RTP/AVP 8 0 101`
- **Симметричный RTP**: отправляете И принимаете на одном порту

#### 1.2.2. Удаленные RTP порты (Exolve)
- **Назначение**: динамически назначается Exolve для каждого звонка
- **Диапазон**: обычно 30000-50000 (примерно)
- **Получение**: из SDP Answer в 200 OK ответе
- **Пример**: `m=audio 41496 RTP/AVP 8 101` означает порт 41496

#### 1.2.3. Симметричный RTP Flow
```
Ваша сторона                          Exolve
┌─────────────────┐                   ┌─────────────────┐
│ SIP: 5060       │ ←── SIP ────────→ │ SIP: 5060       │
│ RTP: 13467      │ ←── RTP ────────→ │ RTP: 41496      │
│ IP: YOUR_IP     │                   │ IP: 80.75.130.100│
└─────────────────┘                   └─────────────────┘

SDP Offer (INVITE):   m=audio 13467 RTP/AVP 8 0 101
SDP Answer (200 OK):  m=audio 41496 RTP/AVP 8 101

RTP Поток:
  Отправляете: YOUR_IP:13467 → 80.75.130.100:41496
  Получаете:   80.75.130.100:41496 → YOUR_IP:13467
```

### 1.3. SIP Авторизация - Критически важно!

#### 1.3.1. Типы запросов и авторизация
**⚠️ НЕ каждый SIP запрос требует авторизации:**

**Требуют авторизации:**
- ✅ **REGISTER** - всегда 401 → auth → 200 OK
- ✅ **INVITE** - обычно 401 → auth → 100/183/200 OK  
- ✅ **BYE** - иногда требует авторизации

**НЕ требуют авторизации:**
- ❌ **ACK** - никогда не авторизуется
- ❌ **CANCEL** - никогда не авторизуется  
- ❌ **100 Trying, 183 Session Progress** - это ответы сервера
- ❌ **OPTIONS** - обычно не требует авторизации

#### 1.3.2. Схема авторизации Exolve
```
1. REGISTER/INVITE без Authorization header
   ↓
2. 401 Unauthorized + WWW-Authenticate: Digest realm="sip.exolve.ru", nonce="...", qop="auth"
   ↓
3. REGISTER/INVITE с Authorization header (Digest authentication)
   ↓
4. 200 OK (или другой успешный ответ)
```

#### 1.3.3. Повторная авторизация
- **Registration**: обновляется каждые 3600 секунд (Expires: 3600)
- **Calls**: каждый INVITE может потребовать отдельную авторизацию
- **Nonce**: может меняться между запросами
- **Realm**: всегда `"sip.exolve.ru"`
```json
{
  "login": "88314XXXXXXXXX",
  "password": "автоматически_сгенерированный",
  "domain": "sip.exolve.ru",
  "username": "88314XXXXXXXXX",
  "cli": "79991112233"
}
```

## 2. SIP Protocol Specification

### 2.1. SIP Registration Flow

#### 2.1.1. Начальный REGISTER запрос
```
REGISTER sip:sip.exolve.ru SIP/2.0
Via: SIP/2.0/UDP YOUR_IP:PORT;branch=z9hG4bK{random};rport
From: <sip:883140123456789@sip.exolve.ru>;tag={random_tag}
To: <sip:883140123456789@sip.exolve.ru>
Call-ID: {unique_call_id}@YOUR_IP
CSeq: 1 REGISTER
Contact: <sip:883140123456789@YOUR_IP:PORT;transport=udp>
Max-Forwards: 70
User-Agent: Custom-SIP-Client/1.0
Expires: 3600
Allow: INVITE, ACK, CANCEL, BYE, OPTIONS
Content-Length: 0
```

#### 2.1.2. Ответ 401 Unauthorized
```
SIP/2.0 401 Unauthorized
WWW-Authenticate: Digest realm="sip.exolve.ru", nonce="{nonce_value}", qop="auth"
```

#### 2.1.3. Аутентифицированный REGISTER
```
REGISTER sip:sip.exolve.ru SIP/2.0
[...стандартные заголовки...]
Authorization: Digest username="883140123456789", realm="sip.exolve.ru", 
               nonce="{nonce}", uri="sip:sip.exolve.ru", 
               response="{md5_hash}", qop=auth, nc=00000001, cnonce="{cnonce}"
```

#### 2.1.4. Digest Authentication - Детальный алгоритм

**Важно**: Exolve использует стандартный **Digest Authentication (RFC 2617)**

**Шаг 1**: Получаем из 401 ответа:
```
WWW-Authenticate: Digest realm="sip.exolve.ru", nonce="AbCdEf123456", qop="auth"
```

**Шаг 2**: Вычисляем response:
```
username = "883140123456789"
password = "your_sip_password"  
realm = "sip.exolve.ru"
method = "REGISTER"  (или "INVITE")
uri = "sip:sip.exolve.ru"  (или конкретный URI для INVITE)
nonce = "AbCdEf123456"  (из WWW-Authenticate)
qop = "auth"
nc = "00000001"  (счетчик запросов, инкрементируется)
cnonce = "8chars_random"  (client nonce, случайная строка)

HA1 = MD5(username:realm:password)
HA2 = MD5(method:uri)  
response = MD5(HA1:nonce:nc:cnonce:qop:HA2)
```

**Шаг 3**: Формируем Authorization header:
```
Authorization: Digest username="883140123456789", 
               realm="sip.exolve.ru", 
               nonce="AbCdEf123456", 
               uri="sip:sip.exolve.ru", 
               response="calculated_md5_hash", 
               qop=auth, 
               nc=00000001, 
               cnonce="8chars_random"
```

**⚠️ Критические моменты:**
- **URI для REGISTER**: всегда `sip:sip.exolve.ru`
- **URI для INVITE**: `sip:79273280718@sip.exolve.ru` (номер назначения)
- **Method**: точно соответствует SIP методу (REGISTER/INVITE)
- **nc**: увеличивается при повторном использовании того же nonce
- **Nonce может измениться** между запросами - парсить из каждого 401

### 2.2. Управление состоянием авторизации

#### 2.2.1. Кеширование credentials
```
SIP Registration State:
├── registered: true/false
├── expires_at: timestamp + 3600 seconds  
├── last_nonce: "сохраненный nonce"
├── nc_counter: инкрементируется для того же nonce
└── credentials: {username, password, realm}

Call State per INVITE:
├── call_id: уникальный для каждого звонка
├── auth_required: true после первого 401
├── call_nonce: nonce для этого конкретного звонка  
└── call_nc: счетчик для этого call_id
```

#### 2.2.2. Последовательность для нового звонка
```
1. INVITE без Authorization
   ↓ (может прийти 401)
2. Если 401: извлекаем nonce, вычисляем Authorization
   ↓
3. INVITE с Authorization header
   ↓ 
4. 100 Trying → 183 Session Progress → 200 OK
   ↓
5. ACK (БЕЗ Authorization!)
   ↓
6. RTP flow начинается
```

### 2.3. Детальный RTP Port Management

#### 2.3.1. Выбор локального RTP порта
```
Варианты привязки RTP сокета:
1. Случайный порт:  socket.bind(('0.0.0.0', 0))  → ОС выберет свободный
2. Фиксированный:   socket.bind(('0.0.0.0', 12000))  → конкретный порт
3. Из диапазона:    socket.bind(('0.0.0.0', random.randint(10000, 20000)))

Рекомендация: используйте диапазон 10000-20000 для предсказуемости
```

#### 2.3.2. Получение удаленного RTP endpoint
**Из SDP Answer в 200 OK:**
```sdp
m=audio 41496 RTP/AVP 8 101
c=IN IP4 80.75.130.100

Парсинг:
├── remote_ip = "80.75.130.100"  (из c= line)
├── remote_port = 41496          (из m= line)  
└── remote_endpoint = (remote_ip, remote_port)
```

#### 2.3.3. Симметричный RTP - как это работает
```
Локальная настройка:
├── bind_ip = "0.0.0.0"           # слушаем на всех интерфейсах
├── bind_port = 13467             # ваш выбранный порт
├── external_ip = "YOUR_PUBLIC_IP" # для SDP
└── rtp_socket = UDP socket

SDP Offer отправляете:
c=IN IP4 YOUR_PUBLIC_IP
m=audio 13467 RTP/AVP 8 0 101

После получения 200 OK с SDP Answer:
remote_ip = "80.75.130.100"
remote_port = 41496

RTP Traffic:
┌─ Отправляете ────┐    ┌─ Получаете ─────┐
│ FROM: ANY:13467  │    │ TO: 0.0.0.0:13467│
│ TO: 80.75.130.100:41496 │ FROM: 80.75.130.100:41496 │
└──────────────────┘    └─────────────────┘

⚠️ Важно: один UDP сокет для двустороннего обмена!
```

#### 2.3.4. NAT и Firewall considerations
```
Проблемы с NAT:
├── Internal IP ≠ External IP в SDP
├── RTP может не проходить through NAT
└── Exolve отправляет на Internal IP из SDP

Решения:
├── STUN/TURN серверы для определения External IP
├── UPnP для автоматического проброса портов  
├── Фиксированная настройка External IP в SDP
└── ICE (Interactive Connectivity Establishment) - сложнее
```

### 2.4. SIP INVITE Flow для исходящих звонков

#### 2.4.1. INVITE с SDP Offer
```
INVITE sip:79273280718@sip.exolve.ru SIP/2.0
Via: SIP/2.0/UDP YOUR_IP:PORT;branch=z9hG4bK{random};rport
From: <sip:883140123456789@sip.exolve.ru>;tag={from_tag}
To: <sip:79273280718@sip.exolve.ru>
Call-ID: {unique_call_id}
CSeq: 1 INVITE
Contact: <sip:883140123456789@YOUR_IP:PORT;transport=udp>
Content-Type: application/sdp
Content-Length: {sdp_length}

[SDP Body - см. раздел 3]
```

#### 2.4.2. Последовательность ответов и нюансы авторизации

**Сценарий 1: Авторизация НЕ требуется (редко)**
```
INVITE → 100 Trying → 183 Session Progress → 200 OK → ACK
```

**Сценарий 2: Требуется авторизация (обычно)**  
```
INVITE → 401 Unauthorized → INVITE(auth) → 100 Trying → 183 Session Progress → 200 OK → ACK
```

**Сценарий 3: Сложный случай**
```
INVITE → 401 Unauthorized → INVITE(auth) → 407 Proxy Authentication Required → INVITE(proxy_auth) → 200 OK → ACK
```

**⚠️ Критически важно:**
- **ACK НИКОГДА не содержит Authorization header** (даже если INVITE требовал авторизации)
- **Call-ID остается тем же** на протяжении всего диалога
- **CSeq инкрементируется**: INVITE(1) → INVITE(2) → ACK(2)
- **Branch в Via меняется** для каждого нового запроса

#### 2.4.3. ACK подтверждение - особенности
```
ACK sip:79273280718@80.75.130.100:5060;transport=udp SIP/2.0
Via: SIP/2.0/UDP YOUR_IP:PORT;branch=z9hG4bK{new_branch};rport
From: <sip:883140123456789@sip.exolve.ru>;tag={from_tag}
To: <sip:79273280718@sip.exolve.ru>;tag={to_tag_from_200OK}
Call-ID: {call_id}
CSeq: 2 ACK
Content-Length: 0
```

**⚠️ Обратите внимание на ACK:**
- **Request-URI**: берется из Contact header в 200 OK (если есть), иначе из To
- **To tag**: ОБЯЗАТЕЛЬНО копируется из 200 OK ответа
- **CSeq**: тот же номер, что и у успешного INVITE
- **NO Authorization**: никогда не добавляется в ACK
- **NO SDP**: обычно не содержит SDP (уже обменялись в INVITE/200OK)

## 3. Session Description Protocol (SDP)

### 3.1. SDP Offer (отправляем в INVITE)
```sdp
v=0
o=CustomSIP 123456 1 IN IP4 YOUR_EXTERNAL_IP
s=SIP Call
c=IN IP4 YOUR_EXTERNAL_IP
t=0 0
m=audio {rtp_port} RTP/AVP 8 0 101
a=rtpmap:8 PCMA/8000
a=rtpmap:0 PCMU/8000
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-15
a=sendrecv
```

### 3.2. SDP Answer (получаем от Exolve в 200 OK)
```sdp
v=0
o=Exolve 1755754606 1755754607 IN IP4 80.75.130.100
s=Exolve
c=IN IP4 80.75.130.100
t=0 0
m=audio 41496 RTP/AVP 8 101
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-15
```

### 3.3. Разбор SDP полей

#### 3.3.1. Session Description
- **v=0** - версия SDP
- **o=** - owner/creator: `username session_id version network_type address_type IP`
- **s=** - session name
- **c=** - connection info: `network_type address_type IP_address`
- **t=** - timing: `0 0` = постоянная сессия

#### 3.3.2. Media Description
- **m=audio** - тип медиа
- **port** - UDP порт для RTP (динамически назначается Exolve)
- **RTP/AVP** - транспортный протокол
- **8 0 101** - список payload types (кодеков)

#### 3.3.3. Media Attributes
- **a=rtpmap:8 PCMA/8000** - Payload Type 8 = PCMA кодек, 8 кГц
- **a=rtpmap:0 PCMU/8000** - Payload Type 0 = PCMU кодек, 8 кГц
- **a=rtpmap:101 telephone-event/8000** - DTMF тоны
- **a=fmtp:101 0-15** - DTMF события 0-15
- **a=sendrecv** - направление медиа (двунаправленное)

## 4. Real-time Transport Protocol (RTP)

### 4.1. RTP Header (12 байт)
```
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|V=2|P|X|  CC   |M|     PT      |       Sequence Number         |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                           Timestamp                           |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|           Synchronization Source (SSRC) identifier            |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

### 4.2. RTP Payload Types
- **PT 0**: PCMU (μ-law) 8000 Hz
- **PT 8**: PCMA (A-law) 8000 Hz ⭐ **Основной для Exolve**
- **PT 101**: telephone-event (DTMF)

### 4.3. RTP Timing
- **Sample Rate**: 8000 Hz для PCMA/PCMU
- **Packet Interval**: 20 мс (стандартный)
- **Samples per Packet**: 160 (8000 Hz × 0.02 сек)
- **Bytes per Packet**: 160 байт для PCMA/PCMU

## 5. Аудио кодеки и форматы

### 5.1. PCMA (A-law) - Основной кодек Exolve
- **Полное название**: Pulse Code Modulation A-law
- **Частота дискретизации**: 8000 Hz
- **Разрядность**: 8 bit (компрессированный из 13-bit linear)
- **Битрейт**: 64 kbps
- **Payload Type**: 8
- **Применение**: Стандарт для европейской телефонии
- **Качество**: Достаточно для речи

### 5.2. PCMU (μ-law) - Альтернативный кодек
- **Полное название**: Pulse Code Modulation μ-law  
- **Частота дискретизации**: 8000 Hz
- **Разрядность**: 8 bit (компрессированный из 14-bit linear)
- **Payload Type**: 0
- **Применение**: Стандарт для американской телефонии

### 5.3. Конвертация аудио форматов

#### 5.3.1. PCMA → Linear PCM → Other Formats
```
RTP Packet (PCMA 8-bit) 
    ↓ audioop.alaw2lin()
Linear PCM (16-bit signed) 
    ↓ audioop.lin2ulaw()
μ-law (8-bit) для ElevenLabs
```

#### 5.3.2. Ресемплинг 8kHz → 16kHz
При необходимости конвертации в PCM 16 кГц для ElevenLabs:
- Входной поток: PCMA 8 кГц (160 samples/20ms)
- Выходной поток: PCM 16 кГц (320 samples/20ms)
- Метод: Linear interpolation или libresample

## 6. Интеграция с ElevenLabs

### 6.1. Форматы аудио для ElevenLabs
**Рекомендуемый для России:**
- **Формат**: μ-law 8000 Hz
- **Размер чанка**: 160 байт (20 мс)
- **Кодирование**: Base64
- **Частота отправки**: каждые 20-50 мс

**Альтернативный (высокое качество):**
- **Формат**: PCM 16-bit 16000 Hz  
- **Размер чанка**: 640 байт (20 мс)
- **Кодирование**: Base64

### 6.2. Поток данных: Exolve → ElevenLabs
```
1. RTP Packet (PCMA, 160 bytes)
   ↓
2. Parse RTP Header (12 bytes)
   ↓  
3. Extract PCMA Payload (160 bytes)
   ↓
4. Convert PCMA → Linear PCM (320 bytes)
   ↓
5. Convert Linear PCM → μ-law (160 bytes)
   ↓
6. Base64 encode
   ↓
7. WebSocket Message: {"user_audio_chunk": "base64_data"}
```

### 6.3. Поток данных: ElevenLabs → Exolve
```
1. WebSocket Message: {"type":"audio","audio_event":{"audio_base_64":"..."}}
   ↓
2. Base64 decode
   ↓
3. Convert μ-law → Linear PCM
   ↓
4. Convert Linear PCM → PCMA
   ↓
5. Create RTP Header (12 bytes)
   ↓
6. Combine Header + PCMA Payload
   ↓
7. Send UDP packet to remote RTP endpoint
```

## 7. Диагностика проблем "тишина в трубке"

### 7.1. Проверка SIP Signaling
#### ✅ Успешная регистрация
- REGISTER → 401 → REGISTER(auth) → 200 OK

#### ✅ Успешный вызов  
- INVITE → 100 Trying → 183 Session Progress → 200 OK → ACK

#### ❌ Возможные проблемы
- **401 без WWW-Authenticate** - неправильные credentials
- **403 Forbidden** - SIP ID заблокирован
- **404 Not Found** - неправильный номер назначения

### 7.2. Проверка SDP Negotiation
#### ✅ Корректный SDP exchange
```
Local SDP Offer:  m=audio 12345 RTP/AVP 8 0 101
Remote SDP Answer: m=audio 41496 RTP/AVP 8 101
Common Codec: PCMA (PT 8) ✓
```

#### ❌ Проблемы SDP
- **Нет общих кодеков** - codec mismatch
- **Неправильный IP в c=** - RTP пойдет не туда
- **Port 0 в SDP** - отклоненный media stream

### 7.3. Проверка RTP Flow

#### ✅ Нормальный RTP поток
```
Outbound RTP: YOUR_IP:local_port → 80.75.130.100:remote_port
Inbound RTP:  80.75.130.100:remote_port → YOUR_IP:local_port
Packets Sent: 1000+
Packets Received: 1000+
```

#### ❌ Проблемы RTP
- **Только исходящий RTP** - проблемы с NAT/Firewall
- **Неправильный remote endpoint** - ошибка парсинга SDP
- **Payload Type mismatch** - отправляем PT 0, ожидается PT 8

### 7.4. Проверка аудио конвертации

#### ✅ Правильная конвертация
```
RTP Input:  PCMA 160 bytes → Linear PCM 320 bytes → μ-law 160 bytes
Output Size: 160 bytes (соответствует 20ms at 8kHz)
Base64 Length: ~213 characters
```

#### ❌ Проблемы конвертации
- **Неправильный размер чанка** - ElevenLabs ожидает определенные размеры
- **Ошибки кодирования** - audioop exceptions
- **Потеря синхронизации** - буферы переполняются

### 7.5. Проверка WebSocket соединения

#### ✅ Здоровое WebSocket соединение  
```
Connection State: OPEN
Messages Sent: audio chunks каждые 20-50ms
Messages Received: agent responses, transcripts
Ping/Pong: активный
```

#### ❌ Проблемы WebSocket
- **Connection Closed 1008** - неправильный формат сообщений
- **No Response** - проблемы с сетью или аутентификацией
- **High Latency** - медленная сеть

## 8. Мониторинг и метрики

### 8.1. SIP метрики
- **Registration Status**: OK/FAILED
- **Call Setup Time**: < 3 секунды
- **SIP Response Codes**: 200, 183, 100 (хорошо), 4xx/5xx (плохо)

### 8.2. RTP метрики  
- **Packet Loss**: < 1%
- **Jitter**: < 30ms
- **Round Trip Time**: < 200ms
- **Codec Usage**: PCMA preferred

### 8.3. ElevenLabs метрики
- **WebSocket Uptime**: > 99%
- **Audio Chunk Rate**: 25-50 chunks/sec
- **Response Latency**: < 500ms
- **Error Rate**: < 1%

## 9. Рекомендации по оптимизации

### 9.1. Сетевая конфигурация
- **Используйте внешний IP** в SDP для c= поля
- **Откройте UDP порты** для RTP (обычно 10000-20000)
- **Настройте NAT traversal** если нужно
- **Минимизируйте network hops** до Exolve серверов

### 9.2. Аудио обработка
- **Буферизация**: минимальная (1-3 чанка)
- **Интервал отправки**: 20-50 мс для ElevenLabs
- **Формат**: μ-law 8kHz для лучшей совместимости с российской телефонией
- **Обработка ошибок**: graceful degradation при сбоях конвертации

### 9.3. WebSocket оптимизация
- **Реконнект**: автоматический при разрыве
- **Пинг/понг**: каждые 30 секунд
- **Сжатие**: отключить для реалтайм аудио
- **Приоритизация**: аудио трафик важнее текста

## 10. Частые ошибки и решения

### 10.1. "Звонок не проходит"
- **Проверить**: SIP credentials, баланс аккаунта, статус SIP ID
- **Решение**: GetAttributes API, проверка логов INVITE/401/403

### 10.2. "Звонок проходит, но тишина"
- **Проверить**: SDP negotiation, RTP flow, codec compatibility
- **Решение**: Логирование SDP, wireshark trace, проверка NAT

### 10.3. "ElevenLabs не отвечает" 
- **Проверить**: WebSocket состояние, формат аудио сообщений
- **Решение**: Проверка размера чанков, base64 encoding, формат JSON

### 10.4. "Плохое качество звука"
- **Проверить**: Packet loss, jitter, codec mismatch
- **Решение**: QoS настройки, сетевая диагностика, оптимизация буферов