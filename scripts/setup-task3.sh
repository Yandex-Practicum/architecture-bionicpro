set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
python3 - <<'PY'
import base64, os, secrets
from pathlib import Path
p = Path('.env')
existing = p.read_text() if p.exists() else ''
names = {line.split('=', 1)[0].strip() for line in existing.splitlines() if '=' in line}
values = {'BIONICPRO_AUTH_CLIENT_SECRET': secrets.token_urlsafe(32),
          'TOKEN_ENCRYPTION_KEY': base64.urlsafe_b64encode(os.urandom(32)).decode()}
with p.open('a') as f:
    if existing and not existing.endswith('\n'): f.write('\n')
    for name, value in values.items():
        if name not in names: f.write(f'{name}={value}\n')
os.chmod(p, 0o600)
PY
mkdir -p .local/tls
if [[ ! -f .local/tls/localhost.key || ! -f .local/tls/localhost.crt ]]; then
  MSYS_NO_PATHCONV=1 openssl req \
    -x509 \
    -newkey rsa:2048 \
    -sha256 \
    -nodes \
    -days 365 \
    -keyout .local/tls/localhost.key \
    -out .local/tls/localhost.crt \
    -subj '/CN=localhost' \
    -addext 'subjectAltName=DNS:localhost,IP:127.0.0.1' \
    -addext 'basicConstraints=critical,CA:TRUE'
fi
echo 'Local .env and TLS certificate prepared. Existing values were preserved.'
