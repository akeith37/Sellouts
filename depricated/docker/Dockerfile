FROM debian:bullseye-slim

# Install system dependencies
RUN apt-get update --fix-missing  && apt-get install -y \
    git \
    curl \
    gnupg \
    build-essential \
    python3-dev \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    libpng-dev \
    ca-certificates \
    fonts-liberation \
    libappindicator3-1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libgdk-pixbuf2.0-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    python3 \
    python3-pip \
    --no-install-recommends && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set environment for X11 forwarding
ENV DISPLAY=:0 \
    PATH="/usr/local/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSER_PATH=0

# Set workdir and copy app files
WORKDIR /app
COPY sellouts.py /app/sellouts.py
COPY requirements.txt /app/requirements.txt

# Install Python packages
RUN pip3 install --upgrade pip setuptools wheel && pip3 install -r requirements.txt

# Install NodeJS NPM Chromium and Playwright
RUN apt-get update && \
    apt-get install -y curl apt-transport-https gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_18.x | bash - && \
    apt-get install -y nodejs && \
    npm install -g npm@10 && \
    apt-get install -y chromium && \
    pip3 install git+https://github.com/microsoft/playwright-python.git
    #pip3 install --pre playwright
    #pip3 install https://github.com/microsoft/playwright-python/releases/download/v1.52.1-dev.20/playwright-1.52.1.dev20+gb98dd6c-py3-none-manylinux2014_aarch64.whl

# Create dummy node file
#RUN mkdir -p /usr/local/lib/python3.9/dist-packages/playwright/driver
#RUN printf '#!/bin/sh\nexit 0\n' > /usr/local/lib/python3.9/dist-packages/playwright/driver/node
#RUN chmod +x /usr/local/lib/python3.9/dist-packages/playwright/driver/node

# Run the script
CMD ["bash"]
