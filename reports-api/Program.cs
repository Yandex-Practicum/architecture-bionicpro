using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Tokens;

var builder = WebApplication.CreateBuilder(args);

var metadataAddress = builder.Configuration["Keycloak:MetadataAddress"]!;
var issuer = builder.Configuration["Keycloak:Issuer"]!;
var chUrl = builder.Configuration["ClickHouse:Url"]!;
var chUser = builder.Configuration["ClickHouse:User"] ?? "default";
var chPassword = builder.Configuration["ClickHouse:Password"] ?? "";

// Add services to the container.
// Learn more about configuring OpenAPI at https://aka.ms/aspnet/openapi
builder.Services.AddOpenApi();

builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(o =>
    {
        o.MetadataAddress = metadataAddress;
        o.RequireHttpsMetadata = false; // FOR DEV ONLY
        o.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidIssuers = [issuer],
            ValidateAudience = false,
            ValidateLifetime = true,
        };
    });
builder.Services.AddAuthorization();

var app = builder.Build();

// Configure the HTTP request pipeline.
if (app.Environment.IsDevelopment())
{
    app.MapOpenApi();
}

app.UseAuthentication();
app.UseAuthorization();

app.MapGet("/reports", async (HttpContext ctx) =>
{
    var username = ctx.User.FindFirst("preferred_username")?.Value;
    if (string.IsNullOrEmpty(username))
        return Results.Unauthorized();

    var realmAccess = ctx.User.FindFirst("realm_access")?.Value ?? "";
    if (!realmAccess.Contains("\"prothetic_user\""))
        return Results.Forbid();

    var date = ctx.Request.Query["date"].ToString();
    var sql =
        "SELECT username, report_date, prosthesis_model, prosthesis_type, " +
        "grips_count, releases_count, mode_switches_count, modes_usage_minutes " +
        "FROM reports.user_prosthesis_daily " +
        "WHERE username = {u:String}" +
        (string.IsNullOrEmpty(date) ? "" : " AND report_date = {d:Date}") +
        " ORDER BY report_date DESC FORMAT JSONEachRow";

    var url = $"{chUrl}/?query={Uri.EscapeDataString(sql)}" +
              $"&param_u={Uri.EscapeDataString(username)}" +
              (string.IsNullOrEmpty(date) ? "" : $"&param_d={Uri.EscapeDataString(date)}");

    using var http = new HttpClient();
    http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue(
        "Basic", Convert.ToBase64String(Encoding.UTF8.GetBytes($"{chUser}:{chPassword}")));
    var body = await http.GetStringAsync(url);

    var rows = body
        .Split('\n', StringSplitOptions.RemoveEmptyEntries)
        .Select(l => JsonSerializer.Deserialize<ReportRow>(l)!)
        .ToList();
    
    if (rows.Count == 0)
        return Results.NotFound(new
        {
            error = "report_not_ready",
            message = "Отчёт ещё формируется. Попробуйте позже."
        });

    return Results.Ok(rows);
}).RequireAuthorization();

app.Run();

public record ReportRow(
    [property: JsonPropertyName("username")] string Username,
    [property: JsonPropertyName("report_date")] string ReportDate,
    [property: JsonPropertyName("prosthesis_model")] string ProsthesisModel,
    [property: JsonPropertyName("prosthesis_type")] string ProsthesisType,
    [property: JsonPropertyName("grips_count")] int GripsCount,
    [property: JsonPropertyName("releases_count")] int ReleasesCount,
    [property: JsonPropertyName("mode_switches_count")] int ModeSwitchesCount,
    [property: JsonPropertyName("modes_usage_minutes")] Dictionary<string, int> ModesUsageMinutes
);