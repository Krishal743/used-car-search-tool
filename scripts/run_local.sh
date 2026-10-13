#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv/bin/python ] || [ ! -f frontend/dist/index.html ]; then
  echo 'Run ./scripts/setup_linux.sh (Linux) or ./scripts/setup_macos.sh (macOS) first.'
  exit 1
fi
# HTTPX uses its bundled CA list by default. Honor Linux's system trust store,
# including any trusted local CA added by the machine administrator.
if [ "$(uname -s)" = Linux ] && [ -z "${SSL_CERT_FILE:-}" ] && [ -f /etc/ssl/certs/ca-certificates.crt ]; then
  export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
fi
port=$(.venv/bin/python - <<'PY'
import errno
import os
import socket
import sys

requested = os.environ.get('MOTORWISE_PORT', '8000')
try:
    start = int(requested)
    if not 1 <= start <= 65535:
        raise ValueError
except ValueError:
    sys.exit('MOTORWISE_PORT must be a number from 1 to 65535.')

ports = [start] if 'MOTORWISE_PORT' in os.environ else range(start, min(start + 11, 65536))
for candidate in ports:
    try:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', candidate))
        print(candidate)
        break
    except OSError as exc:
        if exc.errno != errno.EADDRINUSE:
            sys.exit(f'Cannot check local port {candidate}: {exc}')
else:
    sys.exit('No free local port found. Try MOTORWISE_PORT=8080 ./scripts/run_local.sh')
PY
)
url="http://127.0.0.1:${port}"
echo "Motorwise is starting at ${url}"
if command -v open >/dev/null; then
  (for _ in $(seq 1 40); do if curl -fsS "${url}/api/health" >/dev/null 2>&1; then open "${url}"; break; fi; sleep .5; done) &
elif command -v xdg-open >/dev/null; then
  (for _ in $(seq 1 40); do if curl -fsS "${url}/api/health" >/dev/null 2>&1; then xdg-open "${url}" >/dev/null 2>&1; break; fi; sleep .5; done) &
fi
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port "${port}"
