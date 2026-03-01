# Louise — API server (no SITL in container)
# SITL (ArduPilot Software-in-the-Loop) runs on host. Connect via MAV_CONNECTION (e.g. tcp:host:5760).

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py server.py geo_intel.py ./
COPY app/ app/
COPY autopilot_adapter/ autopilot_adapter/
COPY flystral/ flystral/
COPY helpstral/ helpstral/
COPY louise/ louise/

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
