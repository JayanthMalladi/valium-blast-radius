# Blast-radius entry image
# Build: downloads sqlglot from a pinned tarball (no git, no apt).
# Run: stdlib-only selector with maps + pristine source.

FROM python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

# Fetch the pinned sqlglot source as a tarball and extract it.
RUN python3 -c "\
import urllib.request, tarfile, io, os, hashlib; \
url='https://github.com/tobymao/sqlglot/archive/eb11aec4be8cb2122afe713a4816662c3f0fb2fa.tar.gz'; \
print('downloading', url); \
with urllib.request.urlopen(url) as r: \
    data = r.read(); \
print('downloaded', len(data), 'bytes'); \
with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as tf: \
    tf.extractall('/opt'); \
print('extracted'); \
# move the extracted tree to /opt/sqlglot and strip .git \
src = '/opt/sqlglot-eb11aec4be8cb2122afe713a4816662c3f0fb2fa'; \
os.makedirs('/opt', exist_ok=True); \
if os.path.exists('/opt/sqlglot'): \
    import shutil; shutil.rmtree('/opt/sqlglot'); \
os.rename(src, '/opt/sqlglot'); \
# drop .git noise if any
import shutil; \
for root, dirs, files in os.walk('/opt/sqlglot'): \
    for d in list(dirs): \
        if d == '.git': \
            p = os.path.join(root, d); shutil.rmtree(p, ignore_errors=True); dirs.remove(d) \
" \
 && test -f /opt/sqlglot/sqlglot/__init__.py

COPY selector /opt/selector
COPY maps /opt/maps

ENV BR_MAPS=/opt/maps BR_PRISTINE=/opt/sqlglot BR_DATA=/data
WORKDIR /opt
CMD ["python", "-m", "selector.main"]
