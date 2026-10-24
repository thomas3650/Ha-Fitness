# https://contributors.home-assistant.io/apps/guides/dockerfile/
ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.14-alpine3.24

# uv is only mounted for the install steps; it is not left in the image.
FROM ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 AS uv

FROM ${BUILD_FROM}

ENV \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python \
    UV_PYTHON_DOWNLOADS=never \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

WORKDIR /opt/ha-fitness/server

# Dependencies first, so a code change does not reinstall them.
COPY server/pyproject.toml server/uv.lock ./
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-install-project

COPY server/ ./
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv sync --frozen --no-dev --no-editable

# The base image's /init (s6-overlay) starts CMD with only PATH set; with-contenv passes the container's
# environment on, so the server sees SUPERVISOR_TOKEN and TZ (docs/ha-notes.md, The Supervisor).
CMD ["/usr/bin/with-contenv", "/opt/venv/bin/python", "-m", "ha_fitness_server"]

LABEL \
    io.hass.type="app" \
    org.opencontainers.image.title="Home Assistant App: HA Fitness" \
    org.opencontainers.image.description="Circuit training at home - the server behind the HA Fitness integration." \
    org.opencontainers.image.source="https://github.com/thomas3650/Ha-Fitness" \
    org.opencontainers.image.licenses="MIT"
