# syntax=docker/dockerfile:1
#
# notavis-mipi-trigger — container image for the Streamlit web UI only.
#
# The PySide6 desktop UI is intentionally NOT part of this image: it is a
# native Qt application meant to run directly on the board's HDMI/DSI output
# (see README.md), which does not containerize cleanly (X11/Wayland socket
# passthrough). Run it natively via `vc-trigger-desktop` instead.
#
# Multi-arch build (linux/amd64 + linux/arm64):
#   docker buildx build --platform linux/amd64,linux/arm64 \
#     -t notavis-mipi-trigger:local .
#
# See deploy/DOCKER.md for GPIO device passthrough on real Pi hardware and
# for the mock-mode workflow on non-Pi (e.g. amd64 dev laptop) hosts.

ARG PYTHON_IMAGE=python:3.12-slim-trixie

# --------------------------------------------------------------------- build
FROM ${PYTHON_IMAGE} AS builder

# lgpio ships as a source distribution (SWIG + C sources, no prebuilt
# wheels for any platform) and must be compiled at build time.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        swig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY src ./src

# Build wheels for the project and every runtime dependency (base install,
# no [desktop]/[dev] extras) so the runtime stage can install fully offline.
#
# Two env vars are required to compile lgpio successfully here:
#   - PYPI=1     selects lgpio's self-contained build (statically compiles
#                the bundled liblgpio C sources instead of linking against
#                a system liblgpio, which this base image does not ship).
#   - CFLAGS=... GCC 14+ (Debian Trixie's default) turns lgpio's legacy
#                K&R-style function-pointer usage into hard errors
#                (-Wincompatible-pointer-types, -Wimplicit-function-declaration)
#                and defaults to a stricter C dialect where an empty `()`
#                parameter list means "no arguments" instead of the old
#                "unspecified arguments" -- lgpio 0.2.2.0's C sources rely on
#                the old behaviour. -std=gnu17 restores it; verified against
#                lgpio 0.2.2.0 on 2026-08-14.
RUN pip install --no-cache-dir --upgrade pip wheel && \
    PYPI=1 CFLAGS="-std=gnu17 -Wno-error=incompatible-pointer-types -Wno-error=implicit-function-declaration" \
    pip wheel --no-cache-dir --wheel-dir /wheels .

# ------------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE} AS runtime

LABEL org.opencontainers.image.title="notavis-mipi-trigger" \
      org.opencontainers.image.description="External GPIO/PWM camera trigger for Raspberry Pi — Streamlit web UI" \
      org.opencontainers.image.source="https://github.com/Notavis-GmbH/notavis-mipi-trigger-public" \
      org.opencontainers.image.licenses="MIT"

# Unprivileged runtime user. On real Pi hardware, grant GPIO access via
# `group_add` in docker-compose.yml (see deploy/DOCKER.md) instead of
# running this container as root.
RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin trigger

WORKDIR /app
COPY --from=builder /wheels /wheels

# Install by package name (not "pip install .") so pip resolves the
# pre-built wheel from --find-links instead of re-triggering a PEP 517
# source build, which would need the hatchling build backend from PyPI --
# unavailable here since this stage runs fully offline (--no-index).
RUN pip install --no-cache-dir --no-index --find-links=/wheels notavis-mipi-trigger \
    && rm -rf /wheels

# `streamlit run` needs a script path on disk (it is not started via the
# `vc-trigger-ui` console-script entry point -- see README.md), so the
# source tree is copied in addition to the installed package.
COPY src ./src
RUN chown -R trigger:trigger /app

ENV PYTHONUNBUFFERED=1 \
    VC_TRIGGER_LOG_LEVEL=INFO \
    VC_TRIGGER_MOCK=0 \
    HOME=/home/trigger

USER trigger
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3).status == 200 else 1)"

ENTRYPOINT ["streamlit", "run", "src/vc_trigger/ui.py"]
CMD ["--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true", "--browser.gatherUsageStats=false"]
