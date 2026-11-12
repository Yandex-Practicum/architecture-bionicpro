namespace bionicpro_auth.Session;

public record SessionData(string AccessToken, DateTimeOffset AccessTokenExpiresAt, string ProtectedRefreshToken);