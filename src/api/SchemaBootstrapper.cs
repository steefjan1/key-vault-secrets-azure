using Microsoft.Data.SqlClient;

namespace KeyVaultSecrets.Api;

/// <summary>
/// Creates dbo.Orders with a few rows on first start. Runs in the background
/// so a paused serverless database or a missing SQL user never blocks the
/// host from answering /api/health (azd waits on that).
/// </summary>
public sealed class SchemaBootstrapper : BackgroundService
{
    private readonly IConfiguration _configuration;
    private readonly ILogger<SchemaBootstrapper> _logger;

    public SchemaBootstrapper(IConfiguration configuration, ILogger<SchemaBootstrapper> logger)
    {
        _configuration = configuration;
        _logger = logger;
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var cs = _configuration["Sql:ConnectionString"];
        if (string.IsNullOrWhiteSpace(cs)) return;

        const string sql = """
            IF OBJECT_ID('dbo.Orders') IS NULL
            BEGIN
                CREATE TABLE dbo.Orders (
                    Id INT IDENTITY PRIMARY KEY,
                    Customer NVARCHAR(100) NOT NULL,
                    Amount DECIMAL(10,2) NOT NULL,
                    CreatedUtc DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME());
                INSERT INTO dbo.Orders (Customer, Amount) VALUES ('Contoso', 120.50), ('Fabrikam', 89.99), ('Tailwind', 310.00);
            END
            """;

        for (var attempt = 1; attempt <= 10 && !stoppingToken.IsCancellationRequested; attempt++)
        {
            try
            {
                await using var conn = new SqlConnection(cs);
                await conn.OpenAsync(stoppingToken);
                await using var cmd = conn.CreateCommand();
                cmd.CommandText = sql;
                await cmd.ExecuteNonQueryAsync(stoppingToken);
                _logger.LogInformation("Schema bootstrap done on attempt {Attempt}", attempt);
                return;
            }
            catch (Exception ex) when (!stoppingToken.IsCancellationRequested)
            {
                _logger.LogWarning(ex, "Schema bootstrap attempt {Attempt} failed, retrying in 20 s", attempt);
                await Task.Delay(TimeSpan.FromSeconds(20), stoppingToken);
            }
        }
    }
}
