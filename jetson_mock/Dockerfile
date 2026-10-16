# Standalone image for jetson_mock/nuc_capture_send.py — the NUC-side test
# harness (real webcam -> WebRTC offer -> Django), NOT the Django backend
# (see ../Dockerfile for that) and not built from the repo root.
#
# aiortc/PyAV ship manylinux wheels with ffmpeg statically linked in, so no
# apt-installed ffmpeg/build toolchain is needed here — pip install alone
# is enough. Reading the actual camera still needs the device node passed
# through at `docker run`/compose time (see docker-compose.jetson-mock.yml)
# — nothing in the image can grant that on its own.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY nuc_capture_send.py .

ENTRYPOINT ["python", "nuc_capture_send.py"]
