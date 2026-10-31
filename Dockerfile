# Build environment of the edhiphy pipeline: Debian bookworm (GNU Make 4.3,
# Python 3.11, SQLite with FTS5), the locked Python dependencies, and the
# spellfix1 SQLite extension for the web export.
#
# The image contains no code and no data. The repository and DATA_DIR are
# bind-mounted at run time (see run_docker.sh and README.md); code changes
# need no rebuild, dependency changes (pyproject.toml, uv.lock) do.

FROM ghcr.io/astral-sh/uv:0.11.33 AS uv

FROM debian:bookworm-slim AS compile

RUN set -ex; \
    export DEBIAN_FRONTEND=noninteractive; \
    cd /tmp; \
    sed -i 's/^Types: deb$/& deb-src/' /etc/apt/sources.list.d/debian.sources; \
    apt-get update; \
    apt-get -qy --no-install-recommends install build-essential libsqlite3-dev dpkg-dev; \
    apt-get -qy --no-install-recommends build-dep sqlite3; \
    apt-get source sqlite3; \
    env -C sqlite3*/ gcc -O2 -pipe -s -fPIC -shared ext/misc/spellfix.c -o /tmp/spellfix1.so

FROM debian:bookworm-slim AS tools

RUN set -ex; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update; \
    apt-get -qy --no-install-recommends install ca-certificates make python3 sqlite3; \
    rm -rf /var/lib/apt/lists/*

COPY --from=uv /uv /usr/local/bin/uv

ENV UV_PYTHON=/usr/bin/python3 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

FROM tools

COPY pyproject.toml uv.lock /opt/project/
RUN set -ex; \
    cd /opt/project; \
    uv sync --frozen --no-cache; \
    rm -rf /opt/project

COPY --from=compile /tmp/spellfix1.so /usr/local/lib/sqlite3/spellfix1.so

# The container runs as the host user (docker run --user), who has no home
# directory in the image.
ENV PATH=/opt/venv/bin:$PATH \
    HOME=/tmp \
    PYTHON=python \
    PYTHONDONTWRITEBYTECODE=1 \
    SPELLFIX1=/usr/local/lib/sqlite3/spellfix1

WORKDIR /work
