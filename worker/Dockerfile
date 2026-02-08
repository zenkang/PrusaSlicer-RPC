# ---------- Base image ----------
FROM python:3.11-slim

# ---------- System dependencies ----------
# FIX: Replaced 'libgl1-mesa-glx' with 'libgl1'
RUN apt-get update && apt-get install -y --no-install-recommends \
    prusa-slicer \
    git \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# ---------- Compatibility Fix ----------
# Ensure 'prusaslicer' command works (apt installs it as 'prusa-slicer')
RUN ln -s /usr/bin/prusa-slicer /usr/local/bin/prusaslicer || true

# ---------- App setup ----------
WORKDIR /app
COPY . /app

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir git+https://github.com/ChristophSchranz/Tweaker-3.git

# Create temp directory
RUN mkdir -p temp

# ---------- Run Worker ----------
CMD ["python", "-u", "worker.py"]