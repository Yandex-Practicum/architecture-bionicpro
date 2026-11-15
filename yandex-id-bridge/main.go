package main

import (
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

const maxBody = 1 << 20

type config struct {
	listenAddr, publicURL                           string
	yandexClientID, yandexClientSecret              string
	yandexRedirectURL                               string
	oidcClientID, oidcClientSecret, oidcRedirectURL string
}

type transaction struct {
	keycloakState, keycloakRedirect, nonce, verifier string
	expiresAt                                        time.Time
}

type authorization struct {
	profile   profile
	nonce     string
	expiresAt time.Time
}

type profile struct {
	ID           string `json:"id"`
	Login        string `json:"login"`
	DefaultEmail string `json:"default_email"`
	FirstName    string `json:"first_name"`
	LastName     string `json:"last_name"`
}

type yandexToken struct {
	AccessToken string `json:"access_token"`
}

type server struct {
	cfg          config
	client       *http.Client
	signingKey   *rsa.PrivateKey
	keyID        string
	mu           sync.Mutex
	transactions map[string]transaction
	codes        map[string]authorization
	tokens       map[string]authorization
}

func main() {
	cfg, err := loadConfig()
	if err != nil {
		log.Fatal(err)
	}
	signingKey, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		log.Fatal(err)
	}
	keyID, err := randomString(12)
	if err != nil {
		log.Fatal(err)
	}
	s := &server{
		cfg:          cfg,
		client:       &http.Client{Timeout: 10 * time.Second},
		signingKey:   signingKey,
		keyID:        keyID,
		transactions: make(map[string]transaction),
		codes:        make(map[string]authorization),
		tokens:       make(map[string]authorization),
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /.well-known/openid-configuration", s.discovery)
	mux.HandleFunc("GET /jwks", s.jwks)
	mux.HandleFunc("GET /authorize", s.authorize)
	mux.HandleFunc("GET /callback", s.callback)
	mux.HandleFunc("POST /token", s.token)
	mux.HandleFunc("GET /userinfo", s.userInfo)

	log.Printf("yandex-id-bridge listening on %s", cfg.listenAddr)
	log.Fatal(http.ListenAndServe(cfg.listenAddr, noStore(mux)))
}

func loadConfig() (config, error) {
	cfg := config{
		listenAddr:         env("LISTEN_ADDR", ":8090"),
		publicURL:          strings.TrimRight(env("PUBLIC_URL", "http://localhost:8090"), "/"),
		yandexClientID:     os.Getenv("YANDEX_CLIENT_ID"),
		yandexClientSecret: os.Getenv("YANDEX_CLIENT_SECRET"),
		yandexRedirectURL:  env("YANDEX_REDIRECT_URL", "http://localhost:8090/callback"),
		oidcClientID:       env("OIDC_CLIENT_ID", "bionicpro-keycloak"),
		oidcClientSecret:   os.Getenv("OIDC_CLIENT_SECRET"),
		oidcRedirectURL:    env("OIDC_REDIRECT_URL", "http://localhost:8080/realms/reports-realm/broker/yandex/endpoint"),
	}
	if cfg.yandexClientID == "" || cfg.yandexClientSecret == "" || cfg.oidcClientSecret == "" {
		return config{}, errors.New("YANDEX_CLIENT_ID, YANDEX_CLIENT_SECRET and OIDC_CLIENT_SECRET are required")
	}
	return cfg, nil
}

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func (s *server) authorize(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	if q.Get("response_type") != "code" || q.Get("client_id") != s.cfg.oidcClientID || q.Get("redirect_uri") != s.cfg.oidcRedirectURL || q.Get("state") == "" {
		http.Error(w, "invalid authorization request", http.StatusBadRequest)
		return
	}
	yandexState, err := randomString(32)
	if err != nil {
		http.Error(w, "could not start authorization", http.StatusInternalServerError)
		return
	}
	verifier, err := randomString(64)
	if err != nil {
		http.Error(w, "could not start authorization", http.StatusInternalServerError)
		return
	}

	now := time.Now()
	s.mu.Lock()
	s.cleanup(now)
	s.transactions[yandexState] = transaction{
		keycloakState: q.Get("state"), keycloakRedirect: q.Get("redirect_uri"),
		nonce: q.Get("nonce"), verifier: verifier, expiresAt: now.Add(5 * time.Minute),
	}
	s.mu.Unlock()

	params := url.Values{
		"response_type":         {"code"},
		"client_id":             {s.cfg.yandexClientID},
		"redirect_uri":          {s.cfg.yandexRedirectURL},
		"scope":                 {"login:info login:email"},
		"force_confirm":         {"yes"},
		"state":                 {yandexState},
		"code_challenge":        {pkceChallenge(verifier)},
		"code_challenge_method": {"S256"},
	}
	http.Redirect(w, r, "https://oauth.yandex.ru/authorize?"+params.Encode(), http.StatusFound)
}

func (s *server) callback(w http.ResponseWriter, r *http.Request) {
	state := r.URL.Query().Get("state")
	s.mu.Lock()
	tx, ok := s.transactions[state]
	delete(s.transactions, state)
	s.mu.Unlock()
	if !ok || time.Now().After(tx.expiresAt) {
		http.Error(w, "invalid or expired state", http.StatusBadRequest)
		return
	}
	if oauthError := r.URL.Query().Get("error"); oauthError != "" {
		redirectWithError(w, r, tx, oauthError)
		return
	}
	if r.URL.Query().Get("code") == "" {
		redirectWithError(w, r, tx, "invalid_request")
		return
	}

	accessToken, err := s.exchangeYandexCode(r.URL.Query().Get("code"), tx.verifier)
	if err != nil {
		log.Printf("Yandex code exchange failed: %v", err)
		redirectWithError(w, r, tx, "identity_provider_error")
		return
	}
	p, err := s.getYandexProfile(accessToken)
	if err != nil {
		log.Printf("Yandex profile request failed: %v", err)
		redirectWithError(w, r, tx, "identity_provider_error")
		return
	}
	if p.ID == "" || p.DefaultEmail == "" {
		redirectWithError(w, r, tx, "profile_incomplete")
		return
	}

	code, err := randomString(32)
	if err != nil {
		http.Error(w, "could not complete authorization", http.StatusInternalServerError)
		return
	}
	s.mu.Lock()
	s.codes[code] = authorization{profile: p, nonce: tx.nonce, expiresAt: time.Now().Add(time.Minute)}
	s.mu.Unlock()
	redirect := tx.keycloakRedirect + "?" + url.Values{"code": {code}, "state": {tx.keycloakState}}.Encode()
	http.Redirect(w, r, redirect, http.StatusFound)
}

func (s *server) token(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseForm(); err != nil || r.Form.Get("grant_type") != "authorization_code" ||
		!secureEqual(r.Form.Get("client_id"), s.cfg.oidcClientID) || !secureEqual(r.Form.Get("client_secret"), s.cfg.oidcClientSecret) ||
		r.Form.Get("redirect_uri") != s.cfg.oidcRedirectURL {
		writeJSON(w, http.StatusUnauthorized, map[string]string{"error": "invalid_client"})
		return
	}

	code := r.Form.Get("code")
	s.mu.Lock()
	auth, ok := s.codes[code]
	delete(s.codes, code)
	s.mu.Unlock()
	if !ok || time.Now().After(auth.expiresAt) {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "invalid_grant"})
		return
	}
	accessToken, err := randomString(32)
	if err != nil {
		http.Error(w, "could not issue token", http.StatusInternalServerError)
		return
	}
	auth.expiresAt = time.Now().Add(2 * time.Minute)
	s.mu.Lock()
	s.tokens[accessToken] = auth
	s.mu.Unlock()
	idToken, err := s.idToken(auth)
	if err != nil {
		http.Error(w, "could not issue token", http.StatusInternalServerError)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"access_token": accessToken, "id_token": idToken, "token_type": "Bearer", "expires_in": 120,
	})
}

func (s *server) userInfo(w http.ResponseWriter, r *http.Request) {
	parts := strings.Fields(r.Header.Get("Authorization"))
	if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	s.mu.Lock()
	auth, ok := s.tokens[parts[1]]
	s.mu.Unlock()
	if !ok || time.Now().After(auth.expiresAt) {
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}
	writeJSON(w, http.StatusOK, claims(auth.profile))
}

func (s *server) discovery(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"issuer": s.cfg.publicURL, "authorization_endpoint": s.cfg.publicURL + "/authorize",
		"token_endpoint": s.cfg.publicURL + "/token", "userinfo_endpoint": s.cfg.publicURL + "/userinfo",
		"jwks_uri":                 s.cfg.publicURL + "/jwks",
		"response_types_supported": []string{"code"}, "subject_types_supported": []string{"public"},
		"id_token_signing_alg_values_supported": []string{"RS256"},
	})
}

func (s *server) jwks(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{"keys": []map[string]string{{
		"kty": "RSA", "use": "sig", "alg": "RS256", "kid": s.keyID,
		"n": base64.RawURLEncoding.EncodeToString(s.signingKey.PublicKey.N.Bytes()),
		"e": base64.RawURLEncoding.EncodeToString([]byte{1, 0, 1}),
	}}})
}

func (s *server) exchangeYandexCode(code, verifier string) (string, error) {
	form := url.Values{
		"grant_type": {"authorization_code"}, "code": {code},
		"client_id": {s.cfg.yandexClientID}, "client_secret": {s.cfg.yandexClientSecret},
		"redirect_uri": {s.cfg.yandexRedirectURL}, "code_verifier": {verifier},
	}
	req, _ := http.NewRequest(http.MethodPost, "https://oauth.yandex.ru/token", strings.NewReader(form.Encode()))
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := s.client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("token endpoint returned %d", resp.StatusCode)
	}
	var token yandexToken
	if err := json.NewDecoder(io.LimitReader(resp.Body, maxBody)).Decode(&token); err != nil || token.AccessToken == "" {
		return "", errors.New("invalid token response")
	}
	return token.AccessToken, nil
}

func (s *server) getYandexProfile(accessToken string) (profile, error) {
	req, _ := http.NewRequest(http.MethodGet, "https://login.yandex.ru/info?format=json", nil)
	req.Header.Set("Authorization", "OAuth "+accessToken)
	resp, err := s.client.Do(req)
	if err != nil {
		return profile{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return profile{}, fmt.Errorf("profile endpoint returned %d", resp.StatusCode)
	}
	var p profile
	err = json.NewDecoder(io.LimitReader(resp.Body, maxBody)).Decode(&p)
	return p, err
}

func (s *server) idToken(auth authorization) (string, error) {
	now := time.Now().Unix()
	payload := claims(auth.profile)
	payload["iss"] = s.cfg.publicURL
	payload["aud"] = s.cfg.oidcClientID
	payload["iat"] = now
	payload["exp"] = now + 120
	if auth.nonce != "" {
		payload["nonce"] = auth.nonce
	}
	return signJWT(payload, s.signingKey, s.keyID)
}

func claims(p profile) map[string]any {
	return map[string]any{
		"sub": p.ID, "preferred_username": p.Login, "email": p.DefaultEmail,
		"email_verified": true, "given_name": p.FirstName, "family_name": p.LastName,
	}
}

func signJWT(payload map[string]any, key *rsa.PrivateKey, keyID string) (string, error) {
	token := jwt.NewWithClaims(jwt.SigningMethodRS256, jwt.MapClaims(payload))
	token.Header["kid"] = keyID
	return token.SignedString(key)
	// header, _ := json.Marshal(map[string]string{"alg": "RS256", "typ": "JWT", "kid": keyID})
	// body, err := json.Marshal(payload)
	// if err != nil {
	// 	return "", err
	// }
	// unsigned := base64.RawURLEncoding.EncodeToString(header) + "." + base64.RawURLEncoding.EncodeToString(body)
	// digest := sha256.Sum256([]byte(unsigned))
	// signature, err := rsa.SignPKCS1v15(rand.Reader, key, crypto.SHA256, digest[:])
	// if err != nil {
	// 	return "", err
	// }
	// return unsigned + "." + base64.RawURLEncoding.EncodeToString(signature), nil
}

func redirectWithError(w http.ResponseWriter, r *http.Request, tx transaction, code string) {
	redirect := tx.keycloakRedirect + "?" + url.Values{"error": {code}, "state": {tx.keycloakState}}.Encode()
	http.Redirect(w, r, redirect, http.StatusFound)
}

func (s *server) cleanup(now time.Time) {
	for key, value := range s.transactions {
		if now.After(value.expiresAt) {
			delete(s.transactions, key)
		}
	}
	for key, value := range s.codes {
		if now.After(value.expiresAt) {
			delete(s.codes, key)
		}
	}
	for key, value := range s.tokens {
		if now.After(value.expiresAt) {
			delete(s.tokens, key)
		}
	}
}

func randomString(size int) (string, error) {
	value := make([]byte, size)
	if _, err := rand.Read(value); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(value), nil
}

func pkceChallenge(verifier string) string {
	digest := sha256.Sum256([]byte(verifier))
	return base64.RawURLEncoding.EncodeToString(digest[:])
}

func secureEqual(a, b string) bool {
	return len(a) == len(b) && subtle.ConstantTimeCompare([]byte(a), []byte(b)) == 1
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func noStore(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		next.ServeHTTP(w, r)
	})
}
