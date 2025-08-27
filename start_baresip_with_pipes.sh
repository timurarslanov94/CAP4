#!/bin/bash

echo "🎤 Starting Baresip with Pipe Audio Configuration"
echo "================================================="

# Проверка что pipes существуют
PIPE_IN="/tmp/baresip_audio_in.pcm"
PIPE_OUT="/tmp/baresip_audio_out.pcm"

if [ ! -p "$PIPE_IN" ] || [ ! -p "$PIPE_OUT" ]; then
    echo "❌ Audio pipes not found!"
    echo "   Please run: ./setup_audio_pipes.sh"
    exit 1
fi

# Проверка что мост запущен (проверяем процесс Python)
if ! pgrep -f "run_audio_bridge.py" > /dev/null; then
    echo "⚠️  Warning: Audio bridge doesn't seem to be running!"
    echo "   Please run in another terminal: ./start_ai_bridge.sh"
    echo ""
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Создание конфигурации для baresip с pipes
BARESIP_PIPES_DIR="$HOME/.baresip_pipes"
mkdir -p "$BARESIP_PIPES_DIR"

# Копируем основную конфигурацию
if [ -d "$HOME/.baresip" ]; then
    cp -r "$HOME/.baresip/"* "$BARESIP_PIPES_DIR/" 2>/dev/null
fi

# Создаём специальную конфигурацию для pipes
cat > "$BARESIP_PIPES_DIR/config" << 'EOF'
# Baresip configuration with pipe audio

# Core
poll_method             epoll
sip_trans_bsize         128

# SIP
#sip_listen             0.0.0.0:5060

# Audio - Using pipes for AI bridge (correct directions)
# Baresip writes remote audio to out.pcm (bridge reads it)
# Baresip reads AI audio from in.pcm (bridge writes it)
audio_player            aufile,/tmp/baresip_audio_out.pcm
audio_source            aufile,/tmp/baresip_audio_in.pcm
audio_srate             8000
audio_channels          1
audio_buffer            20
ausrc_latency          20
auplay_latency         20

# Video
#video_source           avformat,nil
#video_display          sdl
video_size              352x288
video_bitrate           512000
video_fps               25.00
video_fullscreen        no

# AVT
rtp_tos                 184
#rtp_ports              10000-20000
#rtp_bandwidth          512-1024
rtcp_mux                no
jitter_buffer_delay     5-10
rtp_stats               no
#rtp_timeout            60

# Network
#dns_server             8.8.8.8:53
#dns_fallback           8.8.4.4:53
net_interface           en0

# Modules to load
module                  stdio.so
module                  cons.so
module                  g711.so
module                  aufile.so
module                  ctrl_tcp.so

# Module parameters
cons_listen             0.0.0.0:5555
ctrl_tcp_listen         0.0.0.0:4444

# Opus codec parameters  
opus_bitrate            28000
opus_stereo             no
opus_sprop_stereo       no
opus_cbr                no
opus_inbandfec          yes
opus_dtx                no
opus_mirror             no
opus_complexity         10
opus_application        audio
opus_samplerate         48000
opus_packet_loss        10

# Speex codec parameters
speex_quality           7
speex_complexity        7
speex_enhancement       0
speex_mode_nb           3
speex_mode_wb           6
speex_vbr               0
speex_vad               0

# NAT Behavior Discovery
natbd_server            stun.l.google.com
natbd_interval          600

# Media NAT
#medianat               turn
#medianat               ice

# STUN
#stun_server            stun.l.google.com:19302

# TURN
#turn_server            turn.example.com:3478
#turn_username          user
#turn_password          pass
EOF

# Добавляем accounts если есть
if [ -f "$HOME/.baresip/accounts" ]; then
    cp "$HOME/.baresip/accounts" "$BARESIP_PIPES_DIR/"
fi

echo "📁 Configuration directory: $BARESIP_PIPES_DIR"
echo "🎵 Audio pipes:"
echo "   Input:  $PIPE_IN"
echo "   Output: $PIPE_OUT"
echo ""
echo "🚀 Starting Baresip..."
echo "   Commands:"
echo "   'd <number>' - dial"
echo "   'h' - hangup"
echo "   'r' - registration info"
echo "   '/quit' - exit"
echo ""

# Запуск baresip с конфигурацией для pipes
baresip -f "$BARESIP_PIPES_DIR" -v
