import asyncio
import base64
import hashlib
import hmac
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from urllib.parse import urlencode
from datetime import date

import profiles

import re
import httpx
import jwt
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

ORIGIN = os.environ.get('PUBLIC_ORIGIN', 'https://localhost:8443').rstrip('/')
ISSUER = os.environ.get(
    'KEYCLOAK_ISSUER',
    'https://localhost:8443/realms/reports-realm'
).rstrip('/')
INTERNAL = os.environ.get('KEYCLOAK_INTERNAL_URL', ISSUER).rstrip('/')
CLIENT_ID = 'bionicpro-auth'
CLIENT_SECRET = os.environ['BIONICPRO_AUTH_CLIENT_SECRET']
CIPHER = Fernet(os.environ['TOKEN_ENCRYPTION_KEY'].encode())
API_URL = os.environ.get('REPORTS_API_URL', 'http://reports-api:8000').rstrip('/')
CDN_URL = os.environ.get(
    'REPORTS_CDN_URL',
    'http://reports-cdn:8080',
).rstrip('/')
SESSION_TTL = 1800
COOKIE = '__Host-bionicpro_session'
LOGIN_COOKIE = '__Host-bionicpro_login'
CALLBACK = ORIGIN + '/auth/callback'
sessions, attempts = {}, {}
lock = asyncio.Lock()

@asynccontextmanager
async def lifespan(app):
    profiles.initialize()
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
        app.state.http = client
        yield

app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

@app.middleware('http')
async def private_responses(request, call_next):
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response

def cookie(response, name, value, age):
    response.set_cookie(name, value, max_age=age, path='/', secure=True, httponly=True, samesite='lax')

def clear(response, name):
    response.delete_cookie(name, path='/', secure=True, httponly=True, samesite='lax')

def prune():
    now = time.time()
    for store in (sessions, attempts):
        for key in list(store):
            if store[key]['expires'] <= now:
                del store[key]

async def token_request(request, fields):
    response = await request.app.state.http.post(INTERNAL + '/protocol/openid-connect/token',
        data={'client_id': CLIENT_ID, 'client_secret': CLIENT_SECRET, **fields})
    response.raise_for_status()
    return response.json()

def save_tokens(session, tokens):
    session['access'] = tokens['access_token']
    session['access_expires'] = time.time() + int(tokens['expires_in'])
    if tokens.get('refresh_token'):
        session['refresh'] = CIPHER.encrypt(tokens['refresh_token'].encode())

@app.get('/health')
async def health():
    return {'status': 'ok'}

@app.get('/auth/login')
async def login():
    state, binding, verifier, nonce = [secrets.token_urlsafe(32) for _ in range(4)]
    async with lock:
        prune()
        attempts[state] = {'binding': binding, 'verifier': verifier, 'nonce': nonce, 'expires': time.time() + 300}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    query = urlencode({'client_id': CLIENT_ID, 'redirect_uri': CALLBACK, 'response_type': 'code',
        'response_mode': 'query', 'scope': 'openid', 'state': state, 'nonce': nonce,
        'code_challenge': challenge, 'code_challenge_method': 'S256'})
    response = RedirectResponse(ISSUER + '/protocol/openid-connect/auth?' + query, status_code=302)
    cookie(response, LOGIN_COOKIE, binding, 300)
    return response

@app.get('/auth/callback')
async def callback(request: Request, state: str = '', code: str = '', error: str = ''):
    async with lock:
        prune()
        attempt = attempts.get(state)
        if not attempt or not hmac.compare_digest(attempt['binding'], request.cookies.get(LOGIN_COOKIE, '')):
            raise HTTPException(400, 'Invalid or expired login state')
        del attempts[state]
    if error or not code:
        response = RedirectResponse(ORIGIN + '/?login_error=1', status_code=302)
        clear(response, LOGIN_COOKIE)
        return response
    try:
        tokens = await token_request(request, {'grant_type': 'authorization_code', 'code': code,
            'redirect_uri': CALLBACK, 'code_verifier': attempt['verifier']})
        keys = await request.app.state.http.get(INTERNAL + '/protocol/openid-connect/certs')
        keys.raise_for_status()
        header = jwt.get_unverified_header(tokens['id_token'])
        jwk = next(k for k in keys.json()['keys'] if k['kid'] == header['kid'])
        claims = jwt.decode(tokens['id_token'], jwt.PyJWK.from_dict(jwk).key, algorithms=['RS256'],
            audience=CLIENT_ID, issuer=ISSUER, options={'require': ['exp', 'iat', 'sub', 'nonce']})
        if not hmac.compare_digest(claims['nonce'], attempt['nonce']):
            raise ValueError('Invalid nonce')
        session = {'expires': time.time() + SESSION_TTL, 'subject': claims['sub'],
                   'consent_required': claims.get('identity_provider') == 'yandex',
                   'csrf': secrets.token_urlsafe(32)}
        save_tokens(session, tokens)
        if 'refresh' not in session:
            raise ValueError('Refresh token missing')
    except (httpx.HTTPError, jwt.PyJWTError, KeyError, StopIteration, ValueError) as exc:
        logging.warning('Authentication failed (%s)', type(exc).__name__)
        raise HTTPException(502, 'Authentication failed') from None
    sid = secrets.token_urlsafe(32)
    async with lock:
        sessions.pop(request.cookies.get(COOKIE), None)
        sessions[sid] = session
    response = RedirectResponse(ORIGIN + '/', status_code=302)
    clear(response, LOGIN_COOKIE)
    cookie(response, COOKIE, sid, SESSION_TTL)
    return response

async def authorized(request):
    # Caller holds lock: refresh and ID rotation are atomic in this single worker.
    prune()
    sid = request.cookies.get(COOKIE)
    session = sessions.get(sid)
    if not session:
        return None, JSONResponse({'detail': 'Authentication required'}, status_code=401)
    if session['access_expires'] <= time.time() + 5:
        try:
            tokens = await token_request(request, {'grant_type': 'refresh_token',
                'refresh_token': CIPHER.decrypt(session['refresh']).decode()})
            save_tokens(session, tokens)
        except (httpx.HTTPError, KeyError, ValueError):
            del sessions[sid]
            response = JSONResponse({'detail': 'Session expired'}, status_code=401)
            clear(response, COOKIE)
            return None, response
    return session, None

def rotate(request, session, response):
    new_id = secrets.token_urlsafe(32)
    sessions.pop(request.cookies.get(COOKIE), None)
    sessions[new_id] = session
    cookie(response, COOKIE, new_id, max(1, int(session['expires'] - time.time())))
    return response

@app.get('/api/me')
async def me(request: Request):
    async with lock:
        session, error = await authorized(request)
        if error is not None:
            return error
        data = {'authenticated': True}
        if session.get('consent_required'):
            data.update(consent_required=True, csrf_token=session['csrf'])
        return rotate(request, session, JSONResponse(data))

@app.get('/api/reports')
async def reports(
    request: Request,
    date_from: date,
    date_to: date,
):
    async with lock:
        session, error = await authorized(request)

        if error is not None:
            return error

        if session.get('consent_required'):
            return rotate(
                request,
                session,
                JSONResponse(
                    {'detail': 'Profile consent is required'},
                    status_code=403,
                ),
            )

        try:
            upstream = await request.app.state.http.get(
                API_URL + '/reports',
                params={
                    'date_from': date_from.isoformat(),
                    'date_to': date_to.isoformat(),
                },
                headers={
                    'Authorization': 'Bearer ' + session['access'],
                },
            )

            if upstream.status_code in (
                200, 400, 401, 403, 409, 422,
            ):
                response = JSONResponse(
                    upstream.json(),
                    status_code=upstream.status_code,
                )
            else:
                response = JSONResponse(
                    {'detail': 'Report service returned an error'},
                    status_code=502,
                )

        except (httpx.HTTPError, ValueError):
            response = JSONResponse(
                {'detail': 'Report service is unavailable'},
                status_code=502,
            )

        return rotate(request, session, response)


@app.post('/api/consent')
async def consent(request: Request):
    async with lock:
        session, error = await authorized(request)
        if error is not None:
            return error
        if request.headers.get('origin') != ORIGIN or not hmac.compare_digest(
                request.headers.get('x-csrf-token', ''), session['csrf']):
            raise HTTPException(403, 'Invalid consent request')
        if not session.get('consent_required'):
            raise HTTPException(409, 'No pending consent')
        try:
            choice = await request.json()
        except ValueError:
            raise HTTPException(400, 'Expected JSON choice') from None
        if not isinstance(choice, dict) or type(choice.get('allow')) is not bool:
            raise HTTPException(400, 'Expected boolean allow')
        if choice['allow']:
            try:
                broker = await request.app.state.http.get(INTERNAL + '/broker/yandex/token',
                    headers={'Authorization': 'Bearer ' + session['access']})
                broker.raise_for_status()
                external_token = broker.json()['access_token']
                response = await request.app.state.http.get('https://login.yandex.ru/info?format=json',
                    headers={'Authorization': 'OAuth ' + external_token})
                response.raise_for_status()
                profiles.save(session['subject'], response.json())
            except (httpx.HTTPError, KeyError, ValueError):
                return rotate(request, session, JSONResponse({'detail': 'Cannot obtain Yandex profile'}, status_code=502))
        # A refusal never requests or stores business profile data.
        session['consent_required'] = False
        return rotate(request, session, JSONResponse({'saved': choice['allow']}))

@app.get('/cdn/reports/{owner}/{filename}')
async def report_file(
    request: Request,
    owner: str,
    filename: str,
):
    async with lock:
        session, error = await authorized(request)

        if error is not None:
            return error

        if session.get('consent_required'):
            return rotate(
                request,
                session,
                JSONResponse(
                    {'detail': 'Profile consent is required'},
                    status_code=403,
                ),
            )

        expected_owner = hashlib.sha256(
            session['subject'].encode('utf-8')
        ).hexdigest()

        if owner != expected_owner:
            raise HTTPException(
                status_code=403,
                detail='Доступ к чужому отчёту запрещён',
            )

        if not re.fullmatch(
            r'\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}_v\d+_cdc1\.json',
            filename,
        ):
            raise HTTPException(
                status_code=404,
                detail='Отчёт не найден',
            )

        try:
            upstream = await request.app.state.http.get(
                CDN_URL + f'/reports/reports/{owner}/{filename}',
                params=list(request.query_params.multi_items()),
            )

            if upstream.status_code == 200:
                response = Response(
                    content=upstream.content,
                    media_type='application/json',
                    headers={
                        'X-Cache-Status': upstream.headers.get(
                            'X-Cache-Status',
                            'UNKNOWN',
                        ),
                    },
                )
            elif upstream.status_code in (403, 404):
                response = JSONResponse(
                    {
                        'detail': (
                            'Файл недоступен. Запросите отчёт повторно.'
                        ),
                    },
                    status_code=upstream.status_code,
                )
            else:
                response = JSONResponse(
                    {'detail': 'Не удалось получить файл отчёта'},
                    status_code=502,
                )

        except httpx.HTTPError:
            response = JSONResponse(
                {'detail': 'Сервис выдачи отчётов недоступен'},
                status_code=502,
            )

        return rotate(request, session, response)