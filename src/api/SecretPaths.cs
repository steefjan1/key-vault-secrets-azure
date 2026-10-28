using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using Azure.Security.KeyVault.Secrets;
using Microsoft.Extensions.Caching.Memory;

namespace KeyVaultSecrets.Api;

/// <summary>
/// Four ways the same secret (ExternalApiKey) reaches the application. Each
/// one answers the question "which value do you hold right now" with a
/// fingerprint, so a rotation can be timed per path without ever printing
/// the secret.
/// </summary>
public sealed class SecretPaths
{
    public const string SecretName = "ExternalApiKey";
    public static readonly string[] Known = ["reference", "provider", "cached", "ondemand"];
    private static readonly TimeSpan CacheTtl = TimeSpan.FromSeconds(60);
    private static readonly DateTimeOffset ProcessStartUtc = Process.GetCurrentProcess().StartTime.ToUniversalTime();

    private readonly IConfiguration _configuration;
    private readonly SecretClient _client;
    private readonly IMemoryCache _cache;
    private readonly ILogger<SecretPaths> _logger;

    public SecretPaths(IConfiguration configuration, SecretClient client, IMemoryCache cache, ILogger<SecretPaths> logger)
    {
        _configuration = configuration;
        _client = client;
        _cache = cache;
        _logger = logger;
    }

    public async Task<object> StatusAsync(CancellationToken ct)
    {
        var reference = Reference();
        var provider = Provider();
        var cached = await CachedAsync(ct);
        var ondemand = await OnDemandAsync(ct);
        return new
        {
            secret = SecretName,
            generatedAtUtc = DateTimeOffset.UtcNow,
            // Makes restarts and the provider's reload timer visible from outside
            processStartUtc = ProcessStartUtc,
            processUptimeSeconds = (int)(DateTimeOffset.UtcNow - ProcessStartUtc).TotalSeconds,
            instance = Environment.GetEnvironmentVariable("WEBSITE_INSTANCE_ID") is { Length: > 8 } id ? id[..8] : "local",
            paths = new { reference, provider, cached, ondemand },
        };
    }

    public async Task<object?> SingleAsync(string path, CancellationToken ct) => path.ToLowerInvariant() switch
    {
        "reference" => Reference(),
        "provider" => Provider(),
        "cached" => await CachedAsync(ct),
        "ondemand" => await OnDemandAsync(ct),
        _ => null,
    };

    // Path 1: App Service resolved "@Microsoft.KeyVault(...)" before the
    // process started. The code cannot tell this from a plain app setting,
    // which is the point, and also why it only changes on restart,
    // on a refresh call, or after the platform's 24 hour re-fetch.
    private PathResult Reference()
    {
        var value = _configuration["ExternalApi:KeyFromReference"];
        var unresolved = value is not null && value.StartsWith("@Microsoft.KeyVault", StringComparison.OrdinalIgnoreCase);
        return new PathResult(
            Path: "reference",
            Source: "App Service Key Vault reference in app settings",
            Fingerprint: unresolved ? null : Fingerprint(value),
            Note: unresolved ? "reference NOT resolved: check keyVaultReferenceIdentity and the Key Vault Secrets User role" : "refreshed on a configuration change or by the platform every 24 h (measured: not by restart, deploy or the refresh API)",
            KeyVaultCallMs: 0);
    }

    // Path 2: Azure.Extensions.AspNetCore.Configuration.Secrets. The key in
    // IConfiguration is the secret name itself.
    private PathResult Provider()
    {
        var value = _configuration[SecretName];
        return new PathResult(
            Path: "provider",
            Source: "AddAzureKeyVault configuration provider",
            Fingerprint: Fingerprint(value),
            Note: value is null ? "secret not loaded: check KeyVault__Uri and the role assignment" : "refreshed on ReloadInterval (Provider__ReloadMinutes)",
            KeyVaultCallMs: 0);
    }

    // Path 3: SecretClient behind an in-memory cache with a TTL. One Key Vault
    // call per TTL window per instance... per concurrent miss. Measured: ten
    // parallel requests on an empty cache made ten SecretGet calls, because
    // GetOrCreateAsync does not serialize misses. Production code wraps the
    // miss in a SemaphoreSlim or uses HybridCache (.NET 9), which does that.
    // Left as is here so the stampede stays measurable with measure/burst.py.
    private async Task<PathResult> CachedAsync(CancellationToken ct)
    {
        var sw = Stopwatch.StartNew();
        var fromVault = false;
        var entry = await _cache.GetOrCreateAsync($"secret:{SecretName}", async e =>
        {
            e.AbsoluteExpirationRelativeToNow = CacheTtl;
            fromVault = true;
            var secret = await _client.GetSecretAsync(SecretName, cancellationToken: ct);
            return new CachedSecret(secret.Value.Value, DateTimeOffset.UtcNow);
        });
        sw.Stop();
        var age = entry is null ? 0 : (int)(DateTimeOffset.UtcNow - entry.LoadedAtUtc).TotalSeconds;
        return new PathResult(
            Path: "cached",
            Source: "SecretClient + IMemoryCache (60 s TTL)",
            Fingerprint: Fingerprint(entry?.Value),
            Note: fromVault ? "fetched from Key Vault on this request" : $"served from cache, age {age} s",
            KeyVaultCallMs: fromVault ? sw.ElapsedMilliseconds : 0);
    }

    // Path 4: SecretClient on every request. Always current, and every
    // request is a SecretGet against the 4,000 per 10 s vault limit.
    private async Task<PathResult> OnDemandAsync(CancellationToken ct)
    {
        var sw = Stopwatch.StartNew();
        try
        {
            var secret = await _client.GetSecretAsync(SecretName, cancellationToken: ct);
            sw.Stop();
            return new PathResult(
                Path: "ondemand",
                Source: "SecretClient.GetSecretAsync per request",
                Fingerprint: Fingerprint(secret.Value.Value),
                Note: $"version {secret.Value.Properties.Version}",
                KeyVaultCallMs: sw.ElapsedMilliseconds);
        }
        catch (Exception ex)
        {
            sw.Stop();
            _logger.LogWarning(ex, "On-demand SecretGet failed");
            return new PathResult("ondemand", "SecretClient.GetSecretAsync per request", null, $"failed: {ex.GetType().Name}", sw.ElapsedMilliseconds);
        }
    }

    private static string? Fingerprint(string? value)
    {
        if (string.IsNullOrEmpty(value)) return null;
        var hash = SHA256.HashData(Encoding.UTF8.GetBytes(value));
        return Convert.ToHexString(hash)[..12].ToLowerInvariant();
    }

    private sealed record CachedSecret(string Value, DateTimeOffset LoadedAtUtc);
}

public sealed record PathResult(string Path, string Source, string? Fingerprint, string Note, long KeyVaultCallMs);
