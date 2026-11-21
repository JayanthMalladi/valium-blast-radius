# Blast-radius entry image.
# Build (network, 4 cores, 8 GB, 10 min): clone sqlglot at the pinned commit.
# Run (no network, 2 cores, read-only, user nobody):
#   python -m selector.main — stdlib only, reads maps + pristine source as text.
# Maps are built from the pinned commit only (never from sample answers).

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

RUN apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

# Clone pristine sqlglot at the pinned commit (source read-only, never imported)
RUN git clone --depth 1 https://github.com/tobymao/sqlglot.git /opt/sqlglot \
 && cd /opt/sqlglot \
 && git fetch origin eb11aec4be8cb2122afe713a4816662c3f0fb2fa \
 && git checkout eb11aec4be8cb2122afe713a4816662c3f0fb2fa \
 && rm -rf /opt/sqlglot/.git /opt/sqlglot/sqlglotc /opt/sqlglot/sqlglot-integration-tests

COPY selector /opt/selector
COPY maps /opt/maps
COPY tools /opt/tools

ENV BR_MAPS=/opt/maps BR_PRISTINE=/opt/sqlglot BR_DATA=/data
WORKDIR /opt
CMD ["python", "-m", "selector.main"]
