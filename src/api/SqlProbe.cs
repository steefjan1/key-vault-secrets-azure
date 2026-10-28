using System.Diagnostics;
using Microsoft.Data.SqlClient;

namespace KeyVaultSecrets.Api;

/// <summary>
/// Opens the database with the managed identity. The connection string holds
/// no password and nothing in it is a secret, so it lives in app settings as
/// plain text and nothing about the database is in Key Vault.
/// </summary>
public sealed class SqlProbe
{
    private readonly string? _connectionString;

    public SqlProbe(IConfiguration configuration)
    {
        _connectionString = configuration["Sql:ConnectionString"];
    }

    public async Task<object> ProbeAsync(CancellationToken ct)
    {
        if (string.IsNullOrWhiteSpace(_connectionString))
        {
            return new { error = "Sql__ConnectionString is not set" };
        }

        var sw = Stopwatch.StartNew();
        await using var conn = new SqlConnection(_connectionString);
        await conn.OpenAsync(ct);
        var openMs = sw.ElapsedMilliseconds;

        await using var cmd = conn.CreateCommand();
        cmd.CommandText = "SELECT SUSER_SNAME() AS principal, (SELECT COUNT(*) FROM dbo.Orders) AS orderCount";
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        await reader.ReadAsync(ct);
        sw.Stop();

        return new
        {
            principal = reader.GetString(0),
            orderCount = reader.GetInt32(1),
            authentication = "Active Directory Default (managed identity, no password)",
            openMs,
            totalMs = sw.ElapsedMilliseconds,
        };
    }
}
