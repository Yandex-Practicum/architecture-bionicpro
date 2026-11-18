using System.Globalization;
using System.Net.Http.Headers;
using System.Text;

using Amazon.Runtime;
using Amazon.S3;
using Amazon.S3.Model;

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

var s3 = new AmazonS3Client(
    new BasicAWSCredentials(
        builder.Configuration["S3:AccessKey"]!,
        builder.Configuration["S3:SecretKey"]!),
    new AmazonS3Config
    {
        ServiceURL = builder.Configuration["S3:ServiceUrl"],
        ForcePathStyle = true,
        AuthenticationRegion = "garage",
        
        RequestChecksumCalculation = RequestChecksumCalculation.WHEN_REQUIRED,
        ResponseChecksumValidation = ResponseChecksumValidation.WHEN_REQUIRED,
    });
var s3Bucket = builder.Configuration["S3:Bucket"] ?? "reports";
var cdnBaseUrl = builder.Configuration["Cdn:BaseUrl"] ?? "http://localhost:8082/reports";


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

    var reportType = ctx.Request.Query["type"].ToString();
    if (string.IsNullOrEmpty(reportType)) reportType = "report_1";
    if (reportType != "report_1")
        return Results.NotFound(new { error = "unknown_report_type", message = $"Тип отчёта '{reportType}' не поддерживается" });

    var to = DateOnly.TryParse(ctx.Request.Query["to"], CultureInfo.InvariantCulture, out var t)
        ? t
        : DateOnly.FromDateTime(DateTime.UtcNow.AddDays(-1));

    var from = DateOnly.TryParse(ctx.Request.Query["from"], CultureInfo.InvariantCulture, out var f)
        ? f
        : to.AddDays(-6);

    if (from > to || to.DayNumber - from.DayNumber > 366)
        return Results.BadRequest(new { error = "invalid_period", message = "Нужен from <= to, диапазон до 366 дней" });

    var key = $"{username}/{from:yyyy-MM-dd}_{to:yyyy-MM-dd}_{reportType}.json";
    var cdnUrl = $"{cdnBaseUrl}/{key}";

    try
    {
        await s3.GetObjectMetadataAsync(s3Bucket, key);
        return Results.Ok(new { url = cdnUrl, cached = true });
    }
    catch (AmazonS3Exception e) when (e.StatusCode == System.Net.HttpStatusCode.NotFound) { }

    var sql =
        "SELECT username, any(prosthesis_model) AS prosthesis_model, any(prosthesis_type) AS prosthesis_type, " +
        "MIN(report_date) AS date_from, MAX(report_date) AS date_to, COUNT() AS days, " +
        "SUM(grips_count) AS grips_total, SUM(releases_count) AS releases_total, SUM(mode_switches_count) AS mode_switches_total, " +
        "ROUND(AVG(grips_count), 1) AS grips_avg, ROUND(AVG(releases_count), 1) AS releases_avg, ROUND(AVG(mode_switches_count), 1) AS mode_switches_avg, " +
        "sumMap(modes_usage_minutes) AS modes_total_minutes " +
        "FROM reports.user_prosthesis_daily " +
        "WHERE username = {u:String} AND report_date BETWEEN {f:Date} AND {t:Date} " +
        "GROUP BY username FORMAT JSONEachRow";

    var url = $"{chUrl}/?query={Uri.EscapeDataString(sql)}" +
              $"&param_u={Uri.EscapeDataString(username)}" +
              $"&param_f={from:yyyy-MM-dd}&param_t={to:yyyy-MM-dd}";

    using var http = new HttpClient();
    http.DefaultRequestHeaders.Authorization = new AuthenticationHeaderValue(
        "Basic", Convert.ToBase64String(Encoding.UTF8.GetBytes($"{chUser}:{chPassword}")));
    var body = await http.GetStringAsync(url);

    if (string.IsNullOrWhiteSpace(body))
        return Results.NotFound(new
        {
            error = "report_not_ready",
            message = "Отчёт ещё формируется. Попробуйте позже."
        });

    await s3.PutObjectAsync(new PutObjectRequest
    {
        BucketName = s3Bucket,
        Key = key,
        ContentBody = body.Trim(),
        ContentType = "application/json",
    });

    return Results.Ok(new { url = cdnUrl, cached = false });
}).RequireAuthorization();

app.Run();