# Pinned to 3.12 to match what the host runs, and slim because the bot needs no
# build toolchain at runtime — all dependencies are pure Python or ship wheels.
FROM python:3.12-slim

# Fail fast and log immediately: without PYTHONUNBUFFERED, `docker logs` shows
# nothing until the buffer flushes, which makes a crash look like a hang.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Requirements first so a code change does not invalidate the dependency layer.
# One image serves both the bot and the dashboard. requirements-web includes
# requirements, so this is the bot's dependencies plus a few MB — cheaper than
# building and maintaining two images that must stay in step.
COPY requirements.txt requirements-web.txt ./
RUN pip install --no-cache-dir -r requirements-web.txt

COPY . .

# Run as a non-root user. A moderation bot parses hostile input by definition,
# so a container escape should not land on root.
RUN useradd --system --uid 10001 qalqon \
    && mkdir -p /data \
    && chown -R qalqon:qalqon /data /app
USER qalqon

# The database lives on a mounted volume, never inside the image — a rebuild
# must not wipe every strike, whitelist and ban record.
VOLUME ["/data"]

# No EXPOSE: the bot polls Telegram outbound and listens on nothing. There is
# no inbound port to publish, and therefore nothing to collide with whatever
# else is running on the host.

CMD ["python", "main.py"]
