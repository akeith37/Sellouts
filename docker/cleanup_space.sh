#!/usr/bin/env bash

# Fail on any error, undefined var, or failed pipe
set -euo pipefail

echo "Starting cleanup at $(date)"

# Identify disk usage before cleanup
echo "Disk usage available before cleanup:"
df -h /

# Reclaim Docker disk space:
echo "Pruning Docker system..."
sudo docker system prune -a --volumes -f

# Clean APT package cache:
echo "Cleaning apt cache and removing orphaned packages..."
sudo apt-get clean
sudo apt-get autoremove -y

# Wipe any leftover partial archives:
sudo rm -rf /var/cache/apt/archives/*
sudo rm -rf /var/cache/apt/archives/partial/*

# Remove pip cache:
echo "Removing pip cache..."
rm -rf ~/.cache/pip

# Remove Playwright browser binaries:
echo "Removing Plawright cache..."
rm -rf ~/.cache/ms-playwright

# Remove npm cache
echo "Removing npm cache..."
rm -rf ~/.npm

# Clear temp files
echo "Removing temp files..."
sudo rm -rf /tmp/*

# Remove project Node modules if present
if [ -d "./node_modules" ]; then
  echo "Removing local node_modules directory..."
  rm -rf ./node_modules
fi

# Show resulting free space
echo
echo "Disk usage after cleanup:"
df -h /
