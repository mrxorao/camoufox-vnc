FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:99 \
    RESOLUTION_WIDTH=1366 \
    RESOLUTION_HEIGHT=768 \
    TZ=Europe/Lisbon \
    PYTHONUNBUFFERED=1

# Install system dependencies, Xvfb, Openbox, x11vnc, noVNC, websockify, Python, fonts and utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    openbox \
    xdotool \
    x11vnc \
    novnc \
    websockify \
    supervisor \
    curl \
    wget \
    gnupg \
    ca-certificates \
    tzdata \
    locales \
    fonts-liberation \
    fonts-dejavu \
    fonts-noto-color-emoji \
    fonts-noto-cjk \
    procps \
    net-tools \
    socat \
    python3 \
    python3-pip \
    python3-venv \
    # Graphical and Firefox/Camoufox dependencies
    libgtk-3-0 \
    libasound2 \
    libdbus-glib-1-2 \
    libxt6 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libgl1-mesa-dri \
    libgl1-mesa-glx \
    mesa-utils \
    && rm -rf /var/lib/apt/lists/*

# Create a Python virtual environment and install Camoufox + Playwright
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir "camoufox[geoip]" playwright

# Download the native Camoufox binaries (Gecko engine with C++ stealth)
RUN python3 -m camoufox fetch

# Create profile, supervisor and Openbox config directories
RUN mkdir -p /root/profile /data/downloads /var/log/supervisor /etc/supervisor/conf.d /etc/xdg/openbox /root/.config/openbox

# Copy Openbox config files
COPY openbox-rc.xml /etc/xdg/openbox/rc.xml
COPY openbox-rc.xml /root/.config/openbox/rc.xml

# Copy Supervisor configs and startup scripts directly into the image
COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY entrypoint.sh /entrypoint.sh
COPY launch-camoufox.py /launch-camoufox.py
COPY launch-x11vnc.sh /launch-x11vnc.sh
RUN chmod +x /entrypoint.sh /launch-x11vnc.sh /launch-camoufox.py

# Automatic noVNC redirect (direct entry without clicking "Connect")
COPY novnc-index.html /usr/share/novnc/index.html

EXPOSE 5800 5900 9377

ENTRYPOINT ["/entrypoint.sh"]
