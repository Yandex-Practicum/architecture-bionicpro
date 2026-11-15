package main

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
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

	"github.com/coreos/go-oidc/v3/oidc"
)

const (
	sessionCookie = "bionicpro_session"
	stateCookie   = "bionicpro_oauth_state"
	maxBody       = 1 << 20
)

type config struct {
	listenAddr, keycloakURL, keycloakPublicURL string
	realm, clientID, clientSecret              string
	redirectURL, frontendURL, reportsURL       string
	sessionTTL                                 time.Duration
	encryptionKey                              []byte
}

type tokenResponse struct {
	AccessToken      string `json:"access_token"`
	RefreshToken     string `json:"refresh_token"`
	IDToken          string `json:"id_token"`
	ExpiresIn        int64  `json:"expires_in"`
	RefreshExpiresIn int64  `json:"refresh_expires_in"`
}

type transaction struct {
	verifier  string
	expiresAt time.Time
}

type session struct {
	mu               sync.Mutex
	accessToken      string
	encryptedRefresh []byte
	accessExpiresAt  time.Time
	sessionExpiresAt time.Time
}

type server struct {
	cfg             config
	httpClient      *http.Client
	aead            cipher.AEAD
	mu              sync.RWMutex
	transactions    map[string]transaction
	sessions        map[string]*session
	idTokenVerifier *oidc.IDTokenVerifier
}

func main() {
	cfg, err := loadConfig()
	if err != nil {
		log.Fatal(err)
	}

	block, err := aes.NewCipher(cfg.encryptionKey)
	if err != nil {
		log.Fatal(err)
	}
	aead, err := cipher.NewGCM(block)
	if err != nil {
		log.Fatal(err)
	}

	issuer := fmt.Sprintf("%s/realms/%s", cfg.keycloakPublicURL, url.PathEscape(cfg.realm))
	keys := oidc.NewRemoteKeySet(context.Background(), fmt.Sprintf("%s/realms/%s/protocol/openid-connect/certs", cfg.keycloakURL, url.PathEscape(cfg.realm)))
	s := &server{
		cfg:             cfg,
		httpClient:      &http.Client{Timeout: 10 * time.Second},
		aead:            aead,
		transactions:    make(map[string]transaction),
		sessions:        make(map[string]*session),
		idTokenVerifier: oidc.NewVerifier(issuer, keys, &oidc.Config{ClientID: cfg.clientID}),
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /auth/login", s.login)
	mux.HandleFunc("GET /auth/callback", s.callback)
	mux.HandleFunc("GET /auth/session", s.sessionStatus)
	mux.HandleFunc("POST /auth/logout", s.logout)
	mux.HandleFunc("GET /reports", s.reports)

	log.Printf("bionicpro-auth listening on %s", cfg.listenAddr)
	log.Fatal(http.ListenAndServe(cfg.listenAddr, securityHeaders(mux)))
}

func loadConfig() (config, error) {
	key, err := base64.RawURLEncoding.DecodeString(os.Getenv("SESSION_ENCRYPTION_KEY"))
	if err != nil || len(key) != 32 {
		return config{}, errors.New("SESSION_ENCRYPTION_KEY must be a base64url-encoded 32-byte key")
	}
	cfg := config{
		listenAddr:        env("LISTEN_ADDR", ":8000"),
		keycloakURL:       strings.TrimRight(env("KEYCLOAK_URL", "http://keycloak:8080"), "/"),
		keycloakPublicURL: strings.TrimRight(env("KEYCLOAK_PUBLIC_URL", "http://localhost:8080"), "/"),
		realm:             env("KEYCLOAK_REALM", "reports-realm"),
		clientID:          env("KEYCLOAK_CLIENT_ID", "reports-frontend"),
		clientSecret:      os.Getenv("KEYCLOAK_CLIENT_SECRET"),
		redirectURL:       env("OAUTH_REDIRECT_URL", "http://localhost:3000/auth/callback"),
		frontendURL:       env("FRONTEND_URL", "http://localhost:3000"),
		reportsURL:        strings.TrimRight(env("REPORTS_API_URL", "http://reports-api:8000"), "/"),
		sessionTTL:        30 * time.Minute,
		encryptionKey:     key,
	}
	if cfg.clientSecret == "" {
		return config{}, errors.New("KEYCLOAK_CLIENT_SECRET is required")
	}
	return cfg, nil
}

func env(name, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}

func (s *server) login(w http.ResponseWriter, r *http.Request) {
	state, err := randomString(32)
	if err != nil {
		http.Error(w, "could not start authentication", http.StatusInternalServerError)
		return
	}
	verifier, err := randomString(64)
	if err != nil {
		http.Error(w, "could not start authentication", http.StatusInternalServerError)
		return
	}

	s.mu.Lock()
	for key, tx := range s.transactions {
		if time.Now().After(tx.expiresAt) {
			delete(s.transactions, key)
		}
	}
	s.transactions[state] = transaction{verifier: verifier, expiresAt: time.Now().Add(5 * time.Minute)}
	s.mu.Unlock()
	setCookie(w, stateCookie, state, 5*time.Minute)

	query := url.Values{
		"client_id":             {s.cfg.clientID},
		"redirect_uri":          {s.cfg.redirectURL},
		"response_type":         {"code"},
		"scope":                 {"openid"},
		"state":                 {state},
		"code_challenge":        {pkceChallenge(verifier)},
		"code_challenge_method": {"S256"},
	}
	http.Redirect(w, r, s.authorizationEndpoint()+"?"+query.Encode(), http.StatusFound)
}

func (s *server) callback(w http.ResponseWriter, r *http.Request) {
	state := r.URL.Query().Get("state")
	cookie, err := r.Cookie(stateCookie)
	if err != nil || state == "" || cookie.Value != state {
		http.Error(w, "invalid OAuth state", http.StatusBadRequest)
		return
	}

	s.mu.Lock()
	tx, ok := s.transactions[state]
	delete(s.transactions, state)
	s.mu.Unlock()
	clearCookie(w, stateCookie)
	if !ok || time.Now().After(tx.expiresAt) || r.URL.Query().Get("code") == "" {
		http.Error(w, "expired or invalid authorization response", http.StatusBadRequest)
		return
	}

	tokens, err := s.exchange(url.Values{
		"grant_type":    {"authorization_code"},
		"code":          {r.URL.Query().Get("code")},
		"redirect_uri":  {s.cfg.redirectURL},
		"code_verifier": {tx.verifier},
	})
	if err != nil {
		log.Printf("authorization code exchange failed: %v", err)
		http.Error(w, "authentication failed", http.StatusBadGateway)
		return
	}
	if err := s.verifyIDToken(r.Context(), tokens); err != nil {
		log.Printf("ID token verification failed: %v", err)
		http.Error(w, "authentication failed", http.StatusUnauthorized)
		return
	}
	sid, err := s.createSession(tokens)
	if err != nil {
		http.Error(w, "could not create session", http.StatusInternalServerError)
		return
	}
	setCookie(w, sessionCookie, sid, s.cfg.sessionTTL)
	http.Redirect(w, r, s.cfg.frontendURL, http.StatusFound)
}

func (s *server) sessionStatus(w http.ResponseWriter, r *http.Request) {
	cookie, err := r.Cookie(sessionCookie)
	if err != nil || !s.sessionExists(cookie.Value) {
		writeJSON(w, http.StatusUnauthorized, map[string]bool{"authenticated": false})
		return
	}
	writeJSON(w, http.StatusOK, map[string]bool{"authenticated": true})
}

func (s *server) logout(w http.ResponseWriter, r *http.Request) {
	if cookie, err := r.Cookie(sessionCookie); err == nil {
		s.mu.Lock()
		delete(s.sessions, cookie.Value)
		s.mu.Unlock()
	}
	clearCookie(w, sessionCookie)
	w.WriteHeader(http.StatusNoContent)
}

func (s *server) reports(w http.ResponseWriter, r *http.Request) {
	accessToken, err := s.authenticate(r)
	if err != nil {
		clearCookie(w, sessionCookie)
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	req, err := http.NewRequestWithContext(r.Context(), http.MethodGet, s.cfg.reportsURL+"/reports", nil)
	if err != nil {
		http.Error(w, "could not create report request", http.StatusInternalServerError)
		return
	}
	req.Header.Set("Authorization", "Bearer "+accessToken)
	resp, err := s.httpClient.Do(req)
	if err != nil {
		log.Printf("reports API request failed: %v", err)
		http.Error(w, "reports service unavailable", http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()
	for _, name := range []string{"Content-Type", "Content-Disposition"} {
		if value := resp.Header.Get(name); value != "" {
			w.Header().Set(name, value)
		}
	}
	w.WriteHeader(resp.StatusCode)
	_, _ = io.Copy(w, resp.Body)
}

func (s *server) createSession(tokens tokenResponse) (string, error) {
	if tokens.AccessToken == "" || tokens.RefreshToken == "" || tokens.ExpiresIn <= 0 {
		return "", errors.New("Keycloak returned incomplete tokens")
	}
	encrypted, err := s.encrypt(tokens.RefreshToken)
	if err != nil {
		return "", err
	}
	sid, err := randomString(32)
	if err != nil {
		return "", err
	}
	now := time.Now()
	expiresAt := now.Add(s.cfg.sessionTTL)
	if tokens.RefreshExpiresIn > 0 && now.Add(time.Duration(tokens.RefreshExpiresIn)*time.Second).Before(expiresAt) {
		expiresAt = now.Add(time.Duration(tokens.RefreshExpiresIn) * time.Second)
	}
	s.mu.Lock()
	s.sessions[sid] = &session{
		accessToken:      tokens.AccessToken,
		encryptedRefresh: encrypted,
		accessExpiresAt:  now.Add(time.Duration(tokens.ExpiresIn) * time.Second),
		sessionExpiresAt: expiresAt,
	}
	s.mu.Unlock()
	return sid, nil
}

func (s *server) authenticate(r *http.Request) (string, error) {
	cookie, err := r.Cookie(sessionCookie)
	if err != nil {
		return "", err
	}
	s.mu.RLock()
	sess := s.sessions[cookie.Value]
	s.mu.RUnlock()
	if sess == nil {
		return "", errors.New("unknown session")
	}

	sess.mu.Lock()
	defer sess.mu.Unlock()
	s.mu.RLock()
	active := s.sessions[cookie.Value] == sess
	s.mu.RUnlock()
	if !active || time.Now().After(sess.sessionExpiresAt) {
		s.mu.Lock()
		delete(s.sessions, cookie.Value)
		s.mu.Unlock()
		return "", errors.New("expired session")
	}
	if time.Now().Add(5 * time.Second).After(sess.accessExpiresAt) {
		refreshToken, err := s.decrypt(sess.encryptedRefresh)
		if err != nil {
			return "", err
		}
		tokens, err := s.exchange(url.Values{
			"grant_type":    {"refresh_token"},
			"refresh_token": {refreshToken},
		})
		if err != nil {
			return "", err
		}
		if tokens.IDToken != "" {
			if err := s.verifyIDToken(r.Context(), tokens); err != nil {
				return "", err
			}
		}
		if tokens.AccessToken == "" || tokens.ExpiresIn <= 0 {
			return "", errors.New("Keycloak returned an incomplete refreshed token")
		}
		if tokens.RefreshToken == "" {
			tokens.RefreshToken = refreshToken
		}
		encrypted, err := s.encrypt(tokens.RefreshToken)
		if err != nil {
			return "", err
		}
		sess.accessToken = tokens.AccessToken
		sess.encryptedRefresh = encrypted
		sess.accessExpiresAt = time.Now().Add(time.Duration(tokens.ExpiresIn) * time.Second)
	}

	return sess.accessToken, nil
}

func (s *server) verifyIDToken(ctx context.Context, tokens tokenResponse) error {
	if tokens.IDToken == "" {
		return errors.New("Keycloak did not return an ID token")
	}
	idToken, err := s.idTokenVerifier.Verify(ctx, tokens.IDToken)
	if err != nil {
		return err
	}
	if idToken.AccessTokenHash != "" {
		return idToken.VerifyAccessToken(tokens.AccessToken)
	}
	return nil
}

func (s *server) sessionExists(sid string) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	sess := s.sessions[sid]
	if sess == nil || time.Now().After(sess.sessionExpiresAt) {
		delete(s.sessions, sid)
		return false
	}
	return true
}

func (s *server) exchange(values url.Values) (tokenResponse, error) {
	values.Set("client_id", s.cfg.clientID)
	values.Set("client_secret", s.cfg.clientSecret)
	req, err := http.NewRequest(http.MethodPost, s.tokenEndpoint(), strings.NewReader(values.Encode()))
	if err != nil {
		return tokenResponse{}, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	resp, err := s.httpClient.Do(req)
	if err != nil {
		return tokenResponse{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, maxBody))
		return tokenResponse{}, fmt.Errorf("token endpoint returned %d: %s", resp.StatusCode, body)
	}
	var tokens tokenResponse
	if err := json.NewDecoder(io.LimitReader(resp.Body, maxBody)).Decode(&tokens); err != nil {
		return tokenResponse{}, err
	}
	return tokens, nil
}

func (s *server) encrypt(value string) ([]byte, error) {
	nonce := make([]byte, s.aead.NonceSize())
	if _, err := rand.Read(nonce); err != nil {
		return nil, err
	}
	return s.aead.Seal(nonce, nonce, []byte(value), nil), nil
}

func (s *server) decrypt(value []byte) (string, error) {
	if len(value) < s.aead.NonceSize() {
		return "", errors.New("invalid encrypted refresh token")
	}
	plain, err := s.aead.Open(nil, value[:s.aead.NonceSize()], value[s.aead.NonceSize():], nil)
	return string(plain), err
}

func (s *server) authorizationEndpoint() string {
	return fmt.Sprintf("%s/realms/%s/protocol/openid-connect/auth", s.cfg.keycloakPublicURL, url.PathEscape(s.cfg.realm))
}

func (s *server) tokenEndpoint() string {
	return fmt.Sprintf("%s/realms/%s/protocol/openid-connect/token", s.cfg.keycloakURL, url.PathEscape(s.cfg.realm))
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

func setCookie(w http.ResponseWriter, name, value string, ttl time.Duration) {
	http.SetCookie(w, &http.Cookie{
		Name: name, Value: value, Path: "/", MaxAge: int(ttl.Seconds()),
		HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode,
	})
}

func clearCookie(w http.ResponseWriter, name string) {
	http.SetCookie(w, &http.Cookie{
		Name: name, Path: "/", MaxAge: -1,
		HttpOnly: true, Secure: true, SameSite: http.SameSiteLaxMode,
	})
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		next.ServeHTTP(w, r)
	})
}
