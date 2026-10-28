using Azure.Core;
using Azure.Extensions.AspNetCore.Configuration.Secrets;
using Azure.Identity;
using Azure.Monitor.OpenTelemetry.AspNetCore;
using Azure.Security.KeyVault.Secrets;
using KeyVaultSecrets.Api;

var builder = WebApplication.CreateBuilder(args);

// One credential for everything. In Azure it resolves to the user-assigned
// managed identity named by AZURE_CLIENT_ID; on a dev box it falls through to
// `az login`. Production code that only ever runs in Azure should new up
// ManagedIdentityCredential directly and skip the probe chain.
TokenCredential credential = new DefaultAzureCredential(new DefaultAzureCredentialOptions
{
    ExcludeInteractiveBrowserCredential = true,
    ExcludeVisualStudioCodeCredential = true,
});

var keyVaultUri = builder.Configuration["KeyVault:Uri"];
var reloadMinutes = int.TryParse(builder.Configuration["Provider:ReloadMinutes"], out var m) ? m : 5;

// Path 2: the configuration provider. Loads EVERY secret the identity may
// read in the vault into IConfiguration at startup and re-reads them on the
// reload interval. Startup fails if the vault is unreachable.
if (!string.IsNullOrWhiteSpace(keyVaultUri))
{
    builder.Configuration.AddAzureKeyVault(
        new Uri(keyVaultUri),
        credential,
        new AzureKeyVaultConfigurationOptions { ReloadInterval = TimeSpan.FromMinutes(reloadMinutes) });
}

builder.Services.AddSingleton(credential);
builder.Services.AddSingleton(sp => new SecretClient(new Uri(keyVaultUri ?? "https://unset.vault.azure.net/"), credential));
builder.Services.AddMemoryCache();
builder.Services.AddSingleton<SecretPaths>();
builder.Services.AddSingleton<SqlProbe>();
builder.Services.AddHostedService<SchemaBootstrapper>();

if (!string.IsNullOrWhiteSpace(builder.Configuration["APPLICATIONINSIGHTS_CONNECTION_STRING"]))
{
    builder.Services.AddOpenTelemetry().UseAzureMonitor();
}

var app = builder.Build();

app.MapGet("/", () => Results.Redirect("/api/secrets/status"));
app.MapGet("/api/health", () => Results.Ok(new { status = "ok", utc = DateTimeOffset.UtcNow }));

// The measurement endpoint. Returns a fingerprint of the ExternalApiKey as
// each loading path currently sees it, never the value itself.
app.MapGet("/api/secrets/status", async (SecretPaths paths, CancellationToken ct) =>
    Results.Ok(await paths.StatusAsync(ct)));

// One path at a time, for load tests against the audit log.
app.MapGet("/api/secrets/{path}", async (string path, SecretPaths paths, CancellationToken ct) =>
{
    var result = await paths.SingleAsync(path, ct);
    return result is null ? Results.NotFound(new { error = "unknown path", known = SecretPaths.Known }) : Results.Ok(result);
});

// The database needs no secret at all: the managed identity IS the login.
app.MapGet("/api/orders", async (SqlProbe sql, CancellationToken ct) => Results.Ok(await sql.ProbeAsync(ct)));

app.Run();
