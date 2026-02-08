# ---------- Base image ----------
FROM python:3.11-slim

# --- FIX 1: PREVENT BUILD HANG (Timezone Prompt) ---
ARG DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC
# ---------------------------------------------------

# ---------- System dependencies ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
    prusa-slicer \
    git \
    ca-certificates \
    libgl1 \
    libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# ---------- Compatibility Fix ----------
RUN ln -s /usr/bin/prusa-slicer /usr/local/bin/prusaslicer || true

# --- FIX 2: CREATE USER FIRST (Permission Fix) ---
# Create non-root user (ID 1000)
RUN useradd -m -u 1000 user

# Create app directory with correct permissions
RUN mkdir -p /app/temp && chown -R user:user /app

# Switch to user context
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

WORKDIR /app

# COPY files with ownership set to the user
COPY --chown=user . /app

# Install Python deps
RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir git+https://github.com/ChristophSchranz/Tweaker-3.git

# Expose health check port
EXPOSE 7860

# ---------- Run Worker ----------
CMD ["python", "-u", "worker.py"]