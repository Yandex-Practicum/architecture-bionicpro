import importlib.util
import json
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient

os.environ.setdefault('BIONICPRO_AUTH_CLIENT_SECRET', 'test-only-secret')
os.environ.setdefault('TOKEN_ENCRYPTION_KEY', Fernet.generate_key().decode())
spec = importlib.util.spec_from_file_location('bff', Path(__file__).with_name('main.py'))
bff = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bff)
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True)
JWK.update(kid='test', alg='RS256', use='sig')

class Sessions(unittest.TestCase):
    def setUp(self):
        bff.sessions.clear()
        bff.attempts.clear()
        self.refreshes = 0
        self.reject_refresh = False
        self.nonce = ''
        self.client = TestClient(bff.app, base_url=bff.ORIGIN)
        self.client.__enter__()
        self.remote = httpx.AsyncClient(transport=httpx.MockTransport(self.upstream))
        bff.app.state.http = self.remote

    def tearDown(self):
        self.client.portal.call(self.remote.aclose)
        self.client.__exit__(None, None, None)

    def upstream(self, request):
        if request.url.path.endswith('/certs'):
            return httpx.Response(200, json={'keys': [JWK]})
        fields = parse_qs(request.content.decode())
        if request.url.path.endswith('/token'):
            if fields['grant_type'] == ['refresh_token']:
                self.refreshes += 1
                self.assertEqual(fields['refresh_token'], ['refresh-secret-1'])
                if self.reject_refresh:
                    return httpx.Response(400, json={'error': 'invalid_grant'})
                return httpx.Response(200, json={'access_token':'access-2','refresh_token':'refresh-secret-2','expires_in':120})
            now = int(time.time())
            id_token = jwt.encode({'iss':bff.ISSUER,'aud':bff.CLIENT_ID,'sub':'user-1',
                'preferred_username':'pilot','nonce':self.nonce,'iat':now,'exp':now+120}, KEY, algorithm='RS256', headers={'kid':'test'})
            return httpx.Response(200, json={'id_token':id_token,'access_token':'access-1',
                                           'refresh_token':'refresh-secret-1','expires_in':120})
        if request.url.path.endswith('/reports'):
            self.assertIn(request.headers['authorization'], ['Bearer access-1','Bearer access-2'])
            return httpx.Response(200, content=b'report,data\n', headers={'content-type':'text/csv'})
        return httpx.Response(204)

    def begin(self):
        r = self.client.get('/auth/login', follow_redirects=False)
        params = parse_qs(urlparse(r.headers['location']).query)
        self.assertEqual(params['code_challenge_method'], ['S256'])
        self.state = params['state'][0]
        self.nonce = params['nonce'][0]
        return r

    def login(self):
        self.begin()
        r = self.client.get('/auth/callback', params={'state':self.state,'code':'test-code'}, follow_redirects=False)
        self.assertEqual(r.status_code,302)
        self.assertNotIn('access-1',r.text + str(r.headers))
        return self.client.cookies.get(bff.COOKIE)

    def test_cookie_and_rotation(self):
        sid = self.login()
        response = self.client.get('/api/me')
        self.assertEqual(response.status_code,200)
        self.assertNotEqual(sid,self.client.cookies.get(bff.COOKIE))
        self.assertNotIn(sid,bff.sessions)
        flags=response.headers['set-cookie']
        for flag in ['HttpOnly','Secure','SameSite=lax','Path=/']: self.assertIn(flag,flags)
        stale=self.client.get('/api/me',headers={'Cookie':bff.COOKIE+'='+sid})
        self.assertEqual(stale.status_code,401)
        self.assertEqual(self.refreshes,0)

    def test_refresh_and_absolute_expiry(self):
        sid=self.login()
        session=bff.sessions[sid]
        deadline=session['expires']
        self.assertNotEqual(session['refresh'], b'refresh-secret-1')
        session['access_expires']=time.time()-1
        r=self.client.get('/api/me')
        self.assertEqual(r.status_code,200)
        updated=bff.sessions[self.client.cookies.get(bff.COOKIE)]
        self.assertEqual(self.refreshes,1)
        self.assertEqual(updated['expires'],deadline)
        self.assertEqual(bff.CIPHER.decrypt(updated['refresh']),b'refresh-secret-2')
        self.assertNotIn('access-2',r.text)

    def test_invalid_refresh_removes_session(self):
        sid=self.login()
        bff.sessions[sid]['access_expires']=0
        self.reject_refresh=True
        self.assertEqual(self.client.get('/api/me').status_code,401)
        self.assertNotIn(sid,bff.sessions)

    def test_expired_session(self):
        sid=self.login()
        bff.sessions[sid]['expires']=0
        self.assertEqual(self.client.get('/api/me').status_code,401)
        self.assertEqual(self.refreshes,0)

    def test_callback_binding_and_replay(self):
        self.begin()
        params={'state':self.state,'code':'test-code'}
        self.assertEqual(self.client.get('/auth/callback',params=params,headers={'Cookie':''}).status_code,400)
        self.assertEqual(self.client.get('/auth/callback',params=params,follow_redirects=False).status_code,302)
        self.assertEqual(self.client.get('/auth/callback',params=params).status_code,400)

    def test_invalid_nonce(self):
        self.begin()
        self.nonce='wrong-nonce'
        self.assertEqual(self.client.get('/auth/callback',params={'state':self.state,'code':'test-code'}).status_code,502)
        self.assertFalse(bff.sessions)

    def test_reports_proxy_and_rotation(self):
        self.assertEqual(self.client.get('/api/reports').status_code,401)
        sid=self.login()
        r=self.client.get('/api/reports')
        self.assertEqual(r.content,b'report,data\n')
        self.assertNotIn(sid,bff.sessions)
        self.assertNotIn('access-1',str(r.headers))

    def test_logout_csrf_and_session_removal(self):
        self.login()
        r=self.client.get('/api/me')
        csrf=r.json()['csrf_token']
        self.assertEqual(self.client.post('/auth/logout').status_code,403)
        self.assertEqual(self.client.post('/auth/logout',headers={'Origin':bff.ORIGIN,'X-CSRF-Token':csrf}).status_code,204)
        self.assertFalse(bff.sessions)
        self.assertEqual(self.client.get('/api/me').status_code,401)

if __name__ == '__main__': unittest.main()
