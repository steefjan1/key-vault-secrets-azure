# Deployment walkthrough and screenshot list

Order of operations for the post, with the screenshots to take. Two `[TODO after deploy]` blocks in the post wait for numbers from steps 5 and 6.

## 1. azd up

- `azd up`, environment `key-vault-secrets`, region `swedencentral`.
- Expect: preprovision prints your UPN and IP; Bicep provisions in 4 to 6 minutes (SQL server is the slow one); `create-sql-user.ps1` prints the SID line; deploy of `api` finishes.
- Screenshot A: terminal with the `create-sql-user.ps1` output (SID, roles).
- Screenshot B: portal, Key Vault, Access control (IAM), role assignments: `id-api` as Secrets User, you as Secrets Officer.

## 2. First calls

- `GET /api/health`, then `/api/secrets/status`.
- Expect four fingerprints, all equal. If `reference` is null with "reference NOT resolved", check `keyVaultReferenceIdentity` on the web app and the Secrets User role; a fresh role assignment can take a minute or two to propagate.
- Screenshot C: the status JSON.
- `GET /api/orders`: expect `principal` = `id-api`, `orderCount` = 3. First call on a paused serverless database may take 30 to 60 s or time out once; retry.
- Screenshot D: the orders JSON.

## 3. Portal: Key Vault reference status

- Web app, Environment variables, the `ExternalApi__KeyFromReference` row shows a green check and "Resolved".
- Screenshot E.

## 4. Audit log

- Log Analytics, run query 1 from `measure/audit.kql`. Expect SecretGet rows for the `id-api` client id (provider at startup, cached, ondemand) and for your UPN if you ran locally.
- Screenshot F.

## 5. Rotation

- `python measure/rotate.py --refresh` (15 min window, then the refresh call).
- Expect ondemand at the first poll, cached within 60 s, provider within 5 min, reference only after the refresh call.
- `python images/make_diagrams.py` regenerates `images/rotation-timeline.png` from `measure/rotate-result.json`.
- Paste the result table into the first `[TODO after deploy]` block.
- Optional second run: `--restart` instead of `--refresh`, to show the restart route.
- Screenshot G: terminal result table.

## 6. Bursts

- Run the three bursts one after the other with a 90 s gap (the audit log only separates them by time window): `python measure/burst.py --path ondemand --count 200`, `Start-Sleep 90`, then `cached`, then `provider`. Query the workspace about 5 minutes later with a `bin(TimeGenerated, 30s)` over the whole span.
- Measured 2026-10-28: ondemand 200, cached 10 (concurrency 10 on an empty cache: a stampede, every parallel miss fetched), provider no rows.
- To see a 429, raise `--count 5000 --concurrency 50` on `ondemand` and look at `ResultSignature`. This is optional; it also throttles anything else that uses the vault.
- Numbers are in the post.
- Screenshot H: audit query result with the three windows.

## 7. Forbidden read (optional, good screenshot)

- Remove the Secrets User assignment for `id-api`, wait two minutes, call `/api/secrets/ondemand`.
- Expect `failed: RequestFailedException` and a `Forbidden` row in query 4. Put the role back.
- Screenshot I.

## 8. Clean up

- `azd down --purge`.

## Post checklist

- Both measurement sections are filled in; `images/rotation-timeline.png` is drawn from `measure/rotation-summary.json`.
- Package versions in the post match `src/api/KeyVaultSecrets.Api.csproj` after `dotnet restore` (not restored in the authoring session).
- Yoast: focus keyphrase "Azure Key Vault managed identity" in title, meta, first paragraph, one H2 and image alt text (done); check readability score and paragraph length.
- No em dashes.
