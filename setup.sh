#!/bin/bash
# =====================================================
# AI Doll "Koupen-chan" - Raspberry Pi Zero 2 W Setup
# Usage: bash setup.sh
# =====================================================
set -e

APP_DIR=/home/pi/doll-ai
BOOT_CFG=/boot/firmware/config.txt   # Bookworm+
[ -f /boot/config.txt ] && BOOT_CFG=/boot/config.txt  # Legacy OS

echo "===== Koupen-chan Setup Start ====="

# -- 1. System packages ------------------------------------
echo "[1/6] Installing system packages..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    python3-pip \
    python3-venv \
    libportaudio2 \
    libportaudiocpp0 \
    portaudio19-dev \
    alsa-utils \
    git

# -- 2. I2S driver config ----------------------------------
echo "[2/6] Configuring I2S drivers..."

# Enable I2S (uncomment if commented out)
if grep -q "^#dtparam=i2s=on" "$BOOT_CFG"; then
    sudo sed -i 's/^#dtparam=i2s=on/dtparam=i2s=on/' "$BOOT_CFG"
    echo "  Enabled dtparam=i2s=on"
elif ! grep -q "^dtparam=i2s=on" "$BOOT_CFG"; then
    echo "dtparam=i2s=on" | sudo tee -a "$BOOT_CFG" > /dev/null
    echo "  Added dtparam=i2s=on"
fi

# googlevoicehat-soundcard overlay (shared for INMP441 + MAX98357A)
# Must be placed BEFORE section headers like [cm4] [cm5]
if ! grep -q "googlevoicehat-soundcard" "$BOOT_CFG"; then
    if grep -q "^\[" "$BOOT_CFG"; then
        sudo sed -i '0,/^\[/{s/^\[/dtoverlay=googlevoicehat-soundcard\n\n[/}' "$BOOT_CFG"
    else
        echo "dtoverlay=googlevoicehat-soundcard" | sudo tee -a "$BOOT_CFG" > /dev/null
    fi
    echo "  Added googlevoicehat-soundcard overlay"
fi

# ALSA config (I2S devices as default + softvol volume control)
# With googlevoicehat-soundcard, both mic and speaker are card 0
sudo tee /etc/asound.conf > /dev/null <<'ALSA'
# doll-ai ALSA config
# Mic: INMP441 (I2S) - card 0
# Speaker: MAX98357A (I2S) - card 0
# Overlay: googlevoicehat-soundcard

pcm.doll_mic_raw {
    type plug
    slave {
        pcm "hw:0,0"
    }
}

pcm.doll_mic {
    type softvol
    slave.pcm "doll_mic_raw"
    control {
        name "Mic Boost"
        card 0
    }
    min_dB -5.0
    max_dB 50.0
}

pcm.doll_spk_raw {
    type plug
    slave {
        pcm "hw:0,0"
    }
}

pcm.doll_spk {
    type softvol
    slave.pcm "doll_spk_raw"
    control {
        name "Speaker Boost"
        card 0
    }
    min_dB -5.0
    max_dB 30.0
}

pcm.!default {
    type asym
    playback.pcm "doll_spk"
    capture.pcm  "doll_mic"
}

ctl.!default {
    type hw
    card 0
}
ALSA

echo "  NOTE: After reboot, verify with:"
echo "     aplay -l   # speaker (should be card 0)"
echo "     arecord -l # mic (should be card 0)"

# -- 3. Python virtual environment --------------------------
echo "[3/6] Creating Python virtual environment..."
python3 -m venv "$APP_DIR/venv"
source "$APP_DIR/venv/bin/activate"
pip install --upgrade pip -q
pip install -r "$APP_DIR/requirements.txt" -q --timeout 120
echo "  Install complete"

# -- 4. API key config -------------------------------------
echo "[4/6] Configuring API key..."
if [ -z "$GEMINI_API_KEY" ]; then
    read -p "Enter your Gemini API key: " API_KEY
    echo "export GEMINI_API_KEY='$API_KEY'" >> /home/pi/.bashrc
    sudo tee /etc/doll-ai.env > /dev/null <<ENV
GEMINI_API_KEY=$API_KEY
ENV
    export GEMINI_API_KEY="$API_KEY"
else
    sudo tee /etc/doll-ai.env > /dev/null <<ENV
GEMINI_API_KEY=$GEMINI_API_KEY
ENV
fi
sudo chmod 600 /etc/doll-ai.env

# -- 5. systemd service ------------------------------------
echo "[5/6] Setting up auto-start service..."
sudo tee /etc/systemd/system/doll-ai.service > /dev/null <<'SERVICE'
[Unit]
Description=AI Doll Koupen-chan
After=network-online.target sound.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/doll-ai
EnvironmentFile=/etc/doll-ai.env
ExecStartPre=/bin/sleep 8
ExecStart=/home/pi/doll-ai/venv/bin/python /home/pi/doll-ai/main.py
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

sudo systemctl daemon-reload
# Do NOT enable by default; enable manually with: sudo systemctl enable doll-ai
echo "  Service installed (not enabled). To enable auto-start:"
echo "    sudo systemctl enable doll-ai"

# -- 6. Create log directory --------------------------------
echo "[6/6] Creating log directory..."
mkdir -p "$APP_DIR/logs"

# -- WiFi check --------------------------------------------
echo ""
echo "Checking WiFi..."
if iwgetid -r &>/dev/null; then
    echo "  WiFi connected: $(iwgetid -r)"
else
    echo "  WARNING: WiFi not connected"
    echo "    Run: sudo raspi-config -> System Options -> Wireless LAN"
fi

# -- Done --------------------------------------------------
echo ""
echo "===== Setup Complete! ====="
echo ""
echo "Next steps:"
echo "1. Reboot:"
echo "   sudo reboot"
echo ""
echo "2. After reboot, check I2S devices:"
echo "   aplay -l    # speaker (card 0)"
echo "   arecord -l  # mic (card 0)"
echo ""
echo "3. Audio test:"
echo "   speaker-test -D plughw:0,0 -t sine -f 440 -l 1"
echo "   arecord -D plughw:0,0 -f S32_LE -r 16000 -c 1 -d 3 /tmp/test.wav"
echo "   aplay -D plughw:0,0 /tmp/test.wav"
echo ""
echo "4. Manual test:"
echo "   source /home/pi/doll-ai/venv/bin/activate"
echo "   python /home/pi/doll-ai/main.py"
echo ""
echo "Service commands:"
echo "  sudo systemctl enable  doll-ai  # enable auto-start"
echo "  sudo systemctl disable doll-ai  # disable auto-start"
echo "  sudo systemctl start   doll-ai  # start"
echo "  sudo systemctl stop    doll-ai  # stop"
echo "  sudo systemctl status  doll-ai  # status"
echo "  journalctl -u doll-ai -f        # logs"
