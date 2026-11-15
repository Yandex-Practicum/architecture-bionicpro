using bionicpro_auth;
using bionicpro_auth.Session;
using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Authentication.OpenIdConnect;

var builder = WebApplication.CreateBuilder(args);


var sessionTtlSeconds = builder.Configuration.GetValue<int>("SESSION_TTL_SECONDS");
var sessionTtl = TimeSpan.FromSeconds(sessionTtlSeconds);
var sessionCookieName = builder.Configuration.GetValue<string>("SESSION_COOKIE_NAME") ?? "bff_session";

var frontendUrl = builder.Configuration.GetValue<string>("FRONTEND_URL") ?? "http://localhost:3000";
var reportsApiUrl = builder.Configuration.GetValue<string>("REPORTS_API_URL") ?? "http://reports-api:8080";

builder.Services.AddAuthentication(options =>
    {
        options.DefaultScheme = CookieAuthenticationDefaults.AuthenticationScheme;
        options.DefaultChallengeScheme = OpenIdConnectDefaults.AuthenticationScheme;
    })
    .AddCookie()
    .AddOpenIdConnect(options =>
    {
        var kcUrlLocal = builder.Configuration.GetSection("KC_URL_INTERNAL").Value;
        var kcUrlPublic = builder.Configuration.GetSection("KC_URL_PUBLIC").Value;
        var kcSecret = builder.Configuration.GetSection("KC_SECRET").Value;
        var kcRealm = builder.Configuration.GetSection("KC_REALM").Value;
        var kcClientId = builder.Configuration.GetSection("KC_CLIENT_ID").Value;
        options.Authority = string.Concat(kcUrlPublic, "/realms/", kcRealm);
        options.MetadataAddress = $"{kcUrlLocal}/realms/{kcRealm}/.well-known/openid-configuration";
        options.TokenValidationParameters.ValidateIssuer = false; //FOR DEV ONLY
        options.RequireHttpsMetadata = false; //FOR DEV ONLY
        options.ClientId = kcClientId;
        options.ClientSecret = kcSecret;
        options.ResponseType = "code";
        options.GetClaimsFromUserInfoEndpoint = true;
        
        options.SaveTokens = true;
        options.Events = new OpenIdConnectEvents
        {
            OnTokenValidated = async context =>
            {
                var resp = context.TokenEndpointResponse;
                if (resp?.AccessToken is null || resp.RefreshToken is null)
                {
                    context.Fail("Token endpoint response is incomplete");
                    return;
                }
                var expiresAt = int.TryParse(resp.ExpiresIn, out var s) ? s : 120;
                
                var store = context.HttpContext.RequestServices.GetRequiredService<SessionStore>();
                var sessionId = store.Create(resp.AccessToken, DateTimeOffset.UtcNow.AddSeconds(expiresAt), resp.RefreshToken);

                context.HttpContext.Response.Cookies.Append("bff_session", sessionId,
                    new CookieOptions { HttpOnly = true, Secure = true, SameSite = SameSiteMode.Lax, MaxAge = sessionTtl });
                context.HandleResponse();
                context.HttpContext.Response.Redirect(frontendUrl);
                await Task.CompletedTask;
            }
        };
    });

builder.Services.AddDataProtection();
builder.Services.AddMemoryCache();
builder.Services.AddSingleton<SessionStore>();
builder.Services.AddHttpClient<KeycloakTokenService>();
builder.Services.AddHttpClient("reports-api");

// Add services to the container.
// Learn more about configuring OpenAPI at https://aka.ms/aspnet/openapi
builder.Services.AddOpenApi();

builder.Services.AddCors(o => o.AddDefaultPolicy(p => p
    .WithOrigins(frontendUrl)
    .AllowCredentials()
    .AllowAnyHeader()));

var app = builder.Build();

app.UseCors();

// Configure the HTTP request pipeline.
if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

app.MapGet("/auth/session", (HttpContext context, SessionStore store) =>
{
    if (!context.Request.Cookies.TryGetValue(sessionCookieName, out var sessionId))
        return Results.Unauthorized();
    return store.Get(sessionId) is null ? Results.Unauthorized() : Results.NoContent();
});

app.MapGet("/auth/login", (IConfiguration config) =>
    Results.Challenge(new AuthenticationProperties
    {
        RedirectUri = config["FRONTEND_URL"] ?? "/"
    }));

app.MapGet("/auth/logout", (HttpContext context, SessionStore store) =>
{
    if (context.Request.Cookies.TryGetValue(sessionCookieName, out var sessionId))
        store.Remove(sessionId);
    
    context.Response.Cookies.Delete(sessionCookieName);
    return Results.SignOut(new AuthenticationProperties { RedirectUri = frontendUrl }, [ OpenIdConnectDefaults.AuthenticationScheme ]);
});

app.MapGet("/api/reports", async (HttpContext context, SessionStore store, KeycloakTokenService tokenService,
    IHttpClientFactory httpClientFactory, ILogger<Program> logger) =>
{
    if (!context.Request.Cookies.TryGetValue(sessionCookieName, out var sessionId))
        return Results.Unauthorized();

    var session = store.Get(sessionId);
    if (session is null) return Results.Unauthorized();

    if (session.AccessTokenExpiresAt <= DateTimeOffset.UtcNow.AddSeconds(-10))
    {
        logger.LogDebug("Access token expired for session {SessionId}, refreshing", sessionId[..8]);
        var refreshToken = store.ExtractRefreshToken(session);
        var refreshed = await tokenService.RefreshAsync(refreshToken);
        if (refreshed is null)
        {
            logger.LogWarning("Refresh failed for session {SessionId}, session removed", sessionId[..8]);
            store.Remove(sessionId);
            return Results.Unauthorized();
        }

        store.Update(sessionId, refreshed.AccessToken, refreshed.ExpiresAt, refreshed.RefreshToken);
        session = store.Get(sessionId)!;
        logger.LogInformation("Token refreshed for session {SessionId}, new expiry {ExpiresAt}",
            sessionId[..8], session.AccessTokenExpiresAt);
    }

    var newSessionId = store.Rotate(sessionId);
    context.Response.Cookies.Append("bff_session", newSessionId,
        new CookieOptions
        {
            HttpOnly = true,
            Secure = true,
            SameSite = SameSiteMode.Lax,
            MaxAge = sessionTtl
        });

    var http = httpClientFactory.CreateClient("reports-api");
    using var request = new HttpRequestMessage(HttpMethod.Get,
        $"{reportsApiUrl}/reports{context.Request.QueryString}");
    request.Headers.Authorization =
        new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", session.AccessToken);

    var response = await http.SendAsync(request);

    if (response.StatusCode == System.Net.HttpStatusCode.NotFound)
        return Results.NotFound(new
        {
            error = "report_not_ready",
            message = "Отчёт ещё формируется. Попробуйте позже."
        });

    if (response.IsSuccessStatusCode)
        return Results.Content(await response.Content.ReadAsStringAsync(), "application/json");

    logger.LogWarning("reports-api вернул {StatusCode}", (int)response.StatusCode);
    return Results.Problem("Ошибка сервиса отчётов", statusCode: 502);

});

app.Run();