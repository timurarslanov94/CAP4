#!/bin/bash

echo "Starting baresip with TCP control..."

# Create minimal config if not exists
mkdir -p ~/.baresip

# Start baresip (modules will be loaded from config)
baresip -f ~/.baresip -v