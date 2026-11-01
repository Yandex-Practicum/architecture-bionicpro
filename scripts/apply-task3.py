import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
config = json.loads(subprocess.check_output(
    ['docker', 'compose', 'config', '--format', 'json'], cwd=ROOT, stderr=subprocess.PIPE))
admin = config['services']['keycloak']['environment']
secret = config['services']['bionicpro-auth']['environment']['BIONICPRO_AUTH_CLIENT_SECRET']
base = 'http://localhost:8080'
for attempt in range(30):
    try:
        with urllib.request.urlopen(base + '/realms/reports-realm', timeout=2):
            break
    except (OSError, urllib.error.URLError):
        time.sleep(2)
else:
    raise SystemExit('Keycloak is not ready')
fields = {'client_id': 'admin-cli', 'grant_type': 'password',
          'username': admin['KEYCLOAK_ADMIN'], 'password': admin['KEYCLOAK_ADMIN_PASSWORD']}
with urllib.request.urlopen(urllib.request.Request(base + '/realms/master/protocol/openid-connect/token',
        data=urllib.parse.urlencode(fields).encode()), timeout=10) as response:
    token = json.load(response)['access_token']
headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
api = base + '/admin/realms/reports-realm'
def call(path, method='GET', data=None):
    body = json.dumps(data).encode() if data is not None else None
    with urllib.request.urlopen(urllib.request.Request(api + path, data=body, headers=headers, method=method), timeout=10) as response:
        content = response.read()
        return json.loads(content) if content else None

call('', 'PUT', {'accessTokenLifespan': 120, 'ssoSessionIdleTimeout': 1800,
                'ssoSessionMaxLifespan': 1800, 'revokeRefreshToken': True, 'refreshTokenMaxReuse': 0})
realm = json.loads((ROOT / 'keycloak/realm-export.json').read_text())
client = next(c for c in realm['clients'] if c['clientId'] == 'bionicpro-auth')
client['secret'] = secret
existing = call('/clients?clientId=bionicpro-auth')
if existing:
    merged = existing[0]
    merged.update(client)
    call('/clients/' + merged['id'], 'PUT', merged)
else:
    call('/clients', 'POST', client)
for old in call('/clients?clientId=reports-frontend'):
    call('/clients/' + old['id'], 'PUT', {'enabled': False})
print('Task 3 applied: confidential client, required S256, access token 120s, refresh rotation; users preserved.')
