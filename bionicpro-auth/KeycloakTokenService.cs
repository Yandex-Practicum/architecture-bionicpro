using System.Text.Json;

namespace bionicpro_auth;

public record RefreshedTokens(string AccessToken, DateTimeOffset ExpiresAt, string RefreshToken);

public class KeycloakTokenService
{
    private readonly HttpClient _http;
    private readonly string _tokenEndpoint, _clientId, _clientSecret;

    public KeycloakTokenService(IConfiguration config, HttpClient http)
    {
        _http = http;
        var kcUrl = config["KC_URL_INTERNAL"] ?? throw new InvalidOperationException("KC_URL_INTERNAL ");
        var realm = config["KC_REALM"] ?? throw new InvalidOperationException("KC_REALM");
        _clientId = config["KC_CLIENT_ID"]!;
        _clientSecret = config["KC_SECRET"]!;
        _tokenEndpoint = $"{kcUrl}/realms/{realm}/protocol/openid-connect/token";
    }

    public async Task<RefreshedTokens?> RefreshAsync(string rawRefreshToken)
    {
        var content = new FormUrlEncodedContent(new Dictionary<string, string>
        {
            ["grant_type"] = "refresh_token",
            ["refresh_token"] = rawRefreshToken,
            ["client_id"] = _clientId,
            ["client_secret"] = _clientSecret
        });
        var resp = await _http.PostAsync(_tokenEndpoint, content);
        if (!resp.IsSuccessStatusCode) return null;

        var json = await resp.Content.ReadFromJsonAsync<JsonElement>();
        return new RefreshedTokens(json.GetProperty("access_token").GetString()!,
            DateTimeOffset.UtcNow.AddSeconds(json.GetProperty("expires_in").GetInt32()),
            json.GetProperty("refresh_token").GetString()!);
    }
}