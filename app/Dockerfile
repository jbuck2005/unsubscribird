FROM python:3.15-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && rm -rf /var/lib/apt/lists/*
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    HF_HOME=/data/hf
# Set by the edge workflow (UNSUB_BUILD=edge) so the site shows the version as 0.28.0-edge; empty for releases.
ARG UNSUB_BUILD=
ENV UNSUB_BUILD=$UNSUB_BUILD
WORKDIR /app
COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements.txt \
 && pip install --index-url https://download.pytorch.org/whl/cpu torch==2.5.1 torchvision==0.20.1 \
 && pip install -r requirements-ml.txt
COPY wbs/ wbs/

EXPOSE 8095
# Same as uvicorn wbs.main:app on port 8095; as a Home Assistant add-on it reads the add-on options first.
CMD ["python", "-m", "wbs.start"]
