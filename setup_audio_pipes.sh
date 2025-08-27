#!/bin/bash

# Setup audio pipes for Baresip <-> Python bridge

PIPE_IN="/tmp/baresip_audio_in.pcm"
PIPE_OUT="/tmp/baresip_audio_out.pcm"

echo "🔧 Setting up audio pipes for Baresip..."

# Remove existing pipes if they exist
if [ -p "$PIPE_IN" ]; then
    echo "Removing existing pipe: $PIPE_IN"
    rm "$PIPE_IN"
fi

if [ -p "$PIPE_OUT" ]; then
    echo "Removing existing pipe: $PIPE_OUT"
    rm "$PIPE_OUT"
fi

# Create named pipes
echo "Creating named pipe: $PIPE_IN"
mkfifo "$PIPE_IN"

echo "Creating named pipe: $PIPE_OUT"
mkfifo "$PIPE_OUT"

# Set permissions
chmod 666 "$PIPE_IN"
chmod 666 "$PIPE_OUT"

echo "✅ Audio pipes created successfully!"
echo ""
echo "Pipes created:"
echo "  Input (to Baresip):   $PIPE_IN"
echo "  Output (from Baresip): $PIPE_OUT"
echo ""
echo "To test the pipes:"
echo "  1. Start Baresip with pipe configuration"
echo "  2. Run: python test_audio_bridge.py"
echo ""
echo "To monitor pipes:"
echo "  cat $PIPE_OUT | xxd | head  # See output from Baresip"
echo "  echo -n > $PIPE_IN          # Send silence to Baresip"