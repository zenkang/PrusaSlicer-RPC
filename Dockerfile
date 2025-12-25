# ---------- Base image ----------
FROM python:3.11-slim

# ---------- System dependencies ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl xz-utils bzip2 git \
    libglib2.0-0 libstdc++6 libgcc-s1 \
    libx11-6 libxext6 libxrender1 libxrandr2 libxi6 libxfixes3 libxcursor1 \
    libgl1 libglu1-mesa libfuse2 libegl1 \
    libgtk2.0-0 libatk1.0-0 libcairo2 libpango-1.0-0 libpangoxft-1.0-0 libgdk-pixbuf-2.0-0 \
    libpangocairo-1.0-0 libpangoft2-1.0-0 libfontconfig1 libfreetype6 \
    libwayland-client0 libwayland-cursor0 libwayland-egl1 \
 && rm -rf /var/lib/apt/lists/*

# ---------- Install PrusaSlicer (CLI) ----------
# Install PrusaSlicer 2.7.1 GTK2 version
RUN mkdir -p /opt/prusaslicer \
 && curl -L -o /tmp/prusaslicer.tar.bz2 \
    "https://github.com/prusa3d/PrusaSlicer/releases/download/version_2.7.1/PrusaSlicer-2.7.1+linux-x64-GTK2-202312121451.tar.bz2" \
 && tar -xjf /tmp/prusaslicer.tar.bz2 -C /opt/prusaslicer --strip-components=1 \
 && rm /tmp/prusaslicer.tar.bz2 \
 && chmod +x /opt/prusaslicer/bin/prusa-slicer \
 && ln -s /opt/prusaslicer/bin/prusa-slicer /usr/local/bin/prusa-slicer \
 && ln -s /opt/prusaslicer/bin/prusa-slicer /usr/local/bin/prusaslicer

# Put PrusaSlicer binaries on PATH
ENV PATH="/opt/prusaslicer/bin:${PATH}"
ENV LD_LIBRARY_PATH="/opt/prusaslicer/lib"

# ---------- App setup ----------
WORKDIR /app
COPY . /app

RUN pip install --no-cache-dir -r requirements.txt \
 && pip install --no-cache-dir git+https://github.com/ChristophSchranz/Tweaker-3.git

# ---------- Run API ----------
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "80"]
