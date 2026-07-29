# syntax=docker/dockerfile:1.7

ARG PYTHON_IMAGE=python:3.14.6-slim-trixie@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6

FROM ${PYTHON_IMAGE} AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

COPY locks/pip-py314.lock locks/pip-py314.lock
RUN python -m pip install --upgrade pip==26.1.2 \
    && python -m pip install --requirement locks/pip-py314.lock

COPY pyproject.toml README.md ./
COPY src/ src/
RUN python -m pip wheel --no-build-isolation --no-deps --wheel-dir /wheels .

FROM ${PYTHON_IMAGE} AS runtime

ARG POLYSIA_BUILD_COMMIT=unknown

ENV APP_ENV=server \
    LIVE_TRADING_ENABLED=false \
    PATH=/home/polysia/.local/bin:${PATH} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TRADING_MODE=DATA_ONLY

RUN groupadd --gid 10001 polysia \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin polysia

WORKDIR /opt/polysia

COPY .env.example .gitignore Makefile README.md pyproject.toml ./
COPY locks/pip-runtime-py314.lock locks/pip-runtime-py314.lock
RUN python -m pip install --upgrade pip==26.1.2 \
    && python -m pip install --requirement locks/pip-runtime-py314.lock

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-deps /wheels/*.whl \
    && rm -rf /wheels \
    && printf '%s\n' "${POLYSIA_BUILD_COMMIT}" > /opt/polysia/BUILD_COMMIT

USER 10001:10001

ENTRYPOINT ["python", "-m", "polysia.cli"]
CMD ["health"]
