# Helpstral & Flystral — API server (no SITL in container)
# SITL (ArduPilot Software-in-the-Loop) is not started here. Run SITL on the host
# or in a separate container; connect via MAV_CONNECTION (e.g. tcp:host:5760).

FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY config.py server.py ./
COPY app/ app/
COPY autopilot_adapter/ autopilot_adapter/
COPY flystral/ flystral/
COPY helpstral/ helpstral/

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
