# Blast-radius entry image
# Build: downloads sqlglot from a pinned tarball (no git, no apt).
# Run: stdlib-only selector with maps + pristine source.

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

RUN python3 -c "import urllib.request; urllib.request.urlretrieve('https://github.com/tobymao/sqlglot/archive/eb11aec4be8cb2122afe713a4816662c3f0fb2fa.tar.gz', '/tmp/sqlglot.tar.gz')" \
 && tar -xzf /tmp/sqlglot.tar.gz -C /opt \
 && test -d /opt/sqlglot-eb11aec4be8cb2122afe713a4816662c3f0fb2fa \
 && rm -rf /opt/sqlglot \
 && mv /opt/sqlglot-eb11aec4be8cb2122afe713a4816662c3f0fb2fa /opt/sqlglot \
 && test -f /opt/sqlglot/sqlglot/__init__.py \
 && rm -f /tmp/sqlglot.tar.gz

COPY selector /opt/selector
COPY maps /opt/maps

ENV BR_MAPS=/opt/maps BR_PRISTINE=/opt/sqlglot BR_DATA=/data BR_NO_CANARY=1
WORKDIR /opt
CMD ["python", "-m", "selector.main"]
