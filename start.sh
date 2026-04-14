#!/bin/bash

# Hostel Excellence Production Boot Script
echo "[INFO] Initializing system for Production..."

# Ensure we're using the virtual environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Print configurations
echo "[INFO] Executing gunicorn with 2 Workers and 4 Threads"
echo "[INFO] Listening on Localhost Port 5000"

# Note: The APScheduler lock ensures only the active "clock" worker fires cron jobs
# Wait format: timeout 120s ensures large models like face_recognition don't timeout on boot
exec gunicorn --workers 2 --threads 4 --timeout 120 --bind 0.0.0.0:5000 app:app
