FROM python:3.12-slim AS sqlite-builder

ARG SQLITE_VERSION=3510300
ARG SQLITE_SHA3=581215771b32ea4c4062e6fb9842c4aa43d0a7fb2b6670ff6fa4ebb807781204

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential ca-certificates curl \
    && curl --fail --location --output /tmp/sqlite.tar.gz \
      "https://sqlite.org/2026/sqlite-autoconf-${SQLITE_VERSION}.tar.gz" \
    && python -c "import hashlib; p='/tmp/sqlite.tar.gz'; actual=hashlib.sha3_256(open(p,'rb').read()).hexdigest(); expected='${SQLITE_SHA3}'; assert actual == expected, (actual, expected)" \
    && mkdir /tmp/sqlite \
    && tar -xzf /tmp/sqlite.tar.gz --strip-components=1 -C /tmp/sqlite \
    && cd /tmp/sqlite \
    && ./configure --prefix=/usr/local --disable-static --enable-shared \
    && make -j2 \
    && make install

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    LD_LIBRARY_PATH=/usr/local/lib

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY --from=sqlite-builder /usr/local/lib/libsqlite3.so* /usr/local/lib/
COPY --from=sqlite-builder /usr/local/bin/sqlite3 /usr/local/bin/sqlite3
RUN ldconfig

COPY pyproject.toml README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN pip install . && python -c "from app.db.session import require_supported_sqlite; require_supported_sqlite()"

RUN mkdir -p /data && chown app:app /data
USER app

ENV DATABASE_URL=sqlite:////data/habit_tracker.db
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
