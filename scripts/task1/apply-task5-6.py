"""Configure required TOTP and the Yandex broker on the existing local Keycloak."""
import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
config = json.loads(subprocess.check_output(['docker', 'compose', 'config', '--format', 'json'], cwd=ROOT, stderr=subprocess.PIPE))
kc = config['services']['keycloak']['environment']
base = 'http://localhost:8080'
for _ in range(30):
    try:
        with urllib.request.urlopen(base + '/realms/reports-realm', timeout=2): break
    except OSError: time.sleep(2)
else: raise SystemExit('Keycloak is not ready')
fields = {'client_id':'admin-cli','grant_type':'password','username':kc['KEYCLOAK_ADMIN'],'password':kc['KEYCLOAK_ADMIN_PASSWORD']}
with urllib.request.urlopen(urllib.request.Request(base+'/realms/master/protocol/openid-connect/token',data=urllib.parse.urlencode(fields).encode()), timeout=10) as r:
    token=json.load(r)['access_token']
headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
api=base+'/admin/realms/reports-realm'
def call(path, method='GET', data=None):
    body=json.dumps(data).encode() if data is not None else None
    with urllib.request.urlopen(urllib.request.Request(api+path,headers=headers,data=body,method=method),timeout=20) as r:
        body=r.read()
        return json.loads(body) if body else None

def executions(alias):
    return call('/authentication/flows/'+urllib.parse.quote(alias,safe='')+'/executions')
def requirement(alias, execution, value):
    call('/authentication/flows/'+urllib.parse.quote(alias,safe='')+'/executions','PUT',{'id':execution['id'],'requirement':value})

browser='bionicpro-browser-otp'
if not any(f['alias']==browser for f in call('/authentication/flows')):
    call('/authentication/flows/browser/copy','POST',{'newName':browser})
for e in executions(browser):
    if e.get('authenticationFlow') and 'Conditional OTP' in e.get('displayName',''):
        requirement(browser,e,'REQUIRED')
    if e.get('providerId')=='conditional-user-configured':
        requirement(browser,e,'DISABLED')
    if e.get('providerId')=='auth-otp-form':
        requirement(browser,e,'REQUIRED')

post='bionicpro-post-broker-otp'
if not any(f['alias']==post for f in call('/authentication/flows')):
    call('/authentication/flows','POST',{'alias':post,'providerId':'basic-flow','topLevel':True,'builtIn':False})
if not any(e.get('providerId')=='auth-otp-form' for e in executions(post)):
    call('/authentication/flows/'+post+'/executions/execution','POST',{'provider':'auth-otp-form'})
for e in executions(post):requirement(post,e,'REQUIRED')

first='bionicpro-first-broker-login'
if not any(f['alias']==first for f in call('/authentication/flows')):
    call('/authentication/flows/first%20broker%20login/copy','POST',{'newName':first})
for e in executions(first):
    if e.get('providerId')=='idp-review-profile':requirement(first,e,'DISABLED')

action=call('/authentication/required-actions/CONFIGURE_TOTP')
action.update(enabled=True,defaultAction=True)
call('/authentication/required-actions/CONFIGURE_TOTP','PUT',action)
call('','PUT',{'browserFlow':browser,'otpPolicyType':'totp','otpPolicyAlgorithm':'HmacSHA1',
              'otpPolicyDigits':6,'otpPolicyPeriod':30,'otpPolicyLookAheadWindow':1})
# All human logins in this realm must go through the browser/OTP flow.
# The deployment's admin-cli in the master realm is unaffected.
for client_config in call('/clients'):
    if client_config.get('directAccessGrantsEnabled'):
        call('/clients/'+client_config['id'],'PUT',{'directAccessGrantsEnabled':False})
# Retire pre-MFA SSO sessions; the BFF is restarted on deployment as well.
call('/logout-all','POST')

clients=call('/clients?clientId=bionicpro-auth')
assert len(clients)==1
client=clients[0]
mapper={'name':'identity-provider','protocol':'openid-connect','protocolMapper':'oidc-usersessionmodel-note-mapper',
        'config':{'user.session.note':'identity_provider','claim.name':'identity_provider','jsonType.label':'String',
                  'id.token.claim':'true','access.token.claim':'false'}}
existing=[m for m in call('/clients/'+client['id']+'/protocol-mappers/models') if m['name']==mapper['name']]
if existing:call('/clients/'+client['id']+'/protocol-mappers/models/'+existing[0]['id'],'PUT',{**mapper,'id':existing[0]['id']})
else:call('/clients/'+client['id']+'/protocol-mappers/models','POST',mapper)

client_id=kc.get('YANDEX_CLIENT_ID','')
client_secret=kc.get('YANDEX_CLIENT_SECRET','')
ready=bool(client_id and client_secret)
idp={'alias':'yandex','displayName':'Яндекс ID','providerId':'yandex','enabled':ready,
     'storeToken':True,'addReadTokenRoleOnCreate':True,'trustEmail':False,
     'firstBrokerLoginFlowAlias':first,'postBrokerLoginFlowAlias':post,
     'config':{'clientId':client_id,'clientSecret':client_secret,'defaultScope':'login:info login:email',
               'clientAuthMethod':'client_secret_post','syncMode':'IMPORT'}}
existing=[p for p in call('/identity-provider/instances') if p['alias']=='yandex']
if existing:
    # Preserve working settings if local secrets have not yet been supplied.
    if not ready and existing[0].get('enabled'):
        idp=existing[0]
        idp.update(firstBrokerLoginFlowAlias=first,postBrokerLoginFlowAlias=post)
    call('/identity-provider/instances/yandex','PUT',idp)
else:call('/identity-provider/instances','POST',idp)
print('Required TOTP configured for password and broker login. Previous SSO sessions retired.')
print('Yandex ID: '+('enabled' if idp['enabled'] else 'prepared but DISABLED: set YANDEX_CLIENT_ID and YANDEX_CLIENT_SECRET in local .env, recreate Keycloak and rerun this script.'))
