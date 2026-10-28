#!/usr/bin/env python3
"""Draws the diagrams for the post from the official Azure service icons.

    pip install cairosvg
    python images/make_diagrams.py

Outputs images/architecture.png, images/secret-paths.png and, when
measure/rotation-summary.json exists, images/rotation-timeline.png.
The icons in images/icons are from Microsoft's Azure Public Service Icons
set (V24), used as-is.
"""
import base64
import json
from pathlib import Path

import cairosvg

HERE = Path(__file__).resolve().parent
ICONS = HERE / "icons"
FONT = "Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif"

BLUE = "#0078D4"
DARK = "#201F1E"
GREY = "#605E5C"
LIGHT = "#F3F2F1"
LINE = "#8A8886"
GREEN = "#107C10"
RED = "#D13438"
AMBER = "#CA5010"
PANEL = "#FFFFFF"


def icon_uri(name):
    data = (ICONS / f"{name}.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")


def icon(name, x, y, size=56, label=None, sub=None, label_dy=14, width=160):
    out = [f'<image href="{icon_uri(name)}" x="{x - size / 2}" y="{y - size / 2}" width="{size}" height="{size}"/>']
    ty = y + size / 2 + label_dy
    if label:
        out.append(f'<text x="{x}" y="{ty}" font-family="{FONT}" font-size="14" font-weight="600" fill="{DARK}" text-anchor="middle">{label}</text>')
        ty += 16
    if sub:
        for line in sub.split("\n"):
            out.append(f'<text x="{x}" y="{ty}" font-family="{FONT}" font-size="12" fill="{GREY}" text-anchor="middle">{line}</text>')
            ty += 14
    return "\n".join(out)


def text(x, y, s, size=13, color=DARK, anchor="start", weight="400", italic=False):
    style = ' font-style="italic"' if italic else ""
    return (f'<text x="{x}" y="{y}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
            f'fill="{color}" text-anchor="{anchor}"{style}>{s}</text>')


def lines(x, y, items, size=12, color=GREY, dy=16, anchor="start"):
    return "\n".join(text(x, y + i * dy, s, size, color, anchor) for i, s in enumerate(items))


def box(x, y, w, h, fill=PANEL, stroke=LINE, dash=None, r=10, sw=1.5):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>'


def arrow(x1, y1, x2, y2, color=BLUE, label=None, lx=None, ly=None, dash=None, width=2, both=False, label_color=None):
    d = f' stroke-dasharray="{dash}"' if dash else ""
    start = ' marker-start="url(#dot)"' if both else ""
    out = [f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" marker-end="url(#arrow-{color[1:]})"{start}{d}/>']
    if label:
        lx = lx if lx is not None else (x1 + x2) / 2
        ly = ly if ly is not None else (y1 + y2) / 2 - 8
        for i, line in enumerate(label.split("\n")):
            out.append(text(lx, ly + i * 14, line, 12, label_color or color, "middle", "600"))
    return "\n".join(out)


def badge(x, y, n, color=BLUE):
    return (f'<circle cx="{x}" cy="{y}" r="11" fill="{color}"/>'
            f'<text x="{x}" y="{y + 4}" font-family="{FONT}" font-size="12" font-weight="700" fill="#fff" text-anchor="middle">{n}</text>')


def defs():
    markers = "".join(
        f'<marker id="arrow-{c[1:]}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{c}"/></marker>'
        for c in (BLUE, GREY, GREEN, RED, AMBER, LINE, DARK))
    return f'<defs>{markers}<marker id="dot" viewBox="0 0 10 10" refX="5" refY="5" markerWidth="5" markerHeight="5"><circle cx="5" cy="5" r="4" fill="{GREY}"/></marker></defs>'


def svg(w, h, body, title):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'{defs()}<rect width="{w}" height="{h}" fill="#FAFAFA"/>'
            f'{text(32, 40, title, 22, DARK, "start", "700")}{body}</svg>')


def render(name, markup, w):
    out = HERE / f"{name}.png"
    cairosvg.svg2png(bytestring=markup.encode("utf-8"), write_to=str(out), output_width=w * 2)
    (HERE / f"{name}.svg").write_text(markup, encoding="utf-8")
    print("wrote", out)


# --------------------------------------------------------------- diagram 1
def architecture():
    W, H = 1200, 640
    b = []
    b.append(text(32, 64, "Managed identity does the authenticating; Key Vault only holds what has no identity of its own.", 14, GREY))

    # Azure boundary
    b.append(box(300, 90, 870, 520, fill="#F5F9FD", stroke="#C7E0F4", dash="6 4", r=14))
    b.append(text(316, 110, "Azure subscription, swedencentral", 12, BLUE, "start", "600"))

    # Developer side
    b.append(box(32, 90, 240, 520, fill=LIGHT, stroke=LINE, r=14))
    b.append(text(48, 114, "Developer machine", 12, GREY, "start", "600"))
    b.append(icon("users", 152, 190, 56, "You", "az login\nDefaultAzureCredential"))
    b.append(icon("code", 152, 330, 56, "ASP.NET Core API", "dotnet run\nno secrets in appsettings"))
    b.append(lines(48, 440, ["Local runs read the vault with", "YOUR identity (Secrets Officer).", "", "Rotation: measure/rotate.py", "az keyvault secret set"], 12, GREY))

    # App Service
    b.append(box(330, 150, 300, 220, fill=PANEL, stroke=LINE, r=12))
    b.append(icon("app-service", 420, 220, 64, "App Service (Linux, B1)", "ASP.NET Core 8 API"))
    b.append(icon("managed-identity", 560, 200, 48, "User-assigned", "managed identity\nid-api"))
    b.append(lines(346, 332, ["AZURE_CLIENT_ID = client id of id-api", "keyVaultReferenceIdentity = id-api"], 11, GREY, 14))

    # Entra and App Insights sit under the App Service box
    b.append(icon("rbac", 400, 490, 56, "Microsoft Entra ID", "issues tokens for id-api\nRBAC decides what they open"))
    b.append(icon("app-insights", 600, 490, 52, "Application Insights", "request + dependency\ntraces"))

    # Key Vault
    b.append(box(720, 150, 220, 220, fill=PANEL, stroke=LINE, r=12))
    b.append(icon("key-vault", 830, 215, 64, "Azure Key Vault", "RBAC, soft delete"))
    b.append(box(738, 296, 184, 58, fill="#EAF3EA", stroke=GREEN, r=8))
    b.append(text(830, 318, "ExternalApiKey", 12, GREEN, "middle", "700"))
    b.append(text(830, 336, "third-party key, no identity", 11, GREY, "middle"))
    b.append(text(830, 350, "id-api: Key Vault Secrets User", 11, GREY, "middle"))

    # SQL
    b.append(box(720, 400, 220, 190, fill=PANEL, stroke=LINE, r=12))
    b.append(icon("sql-database", 830, 455, 60, "Azure SQL (serverless)", "Entra-only authentication"))
    b.append(box(738, 530, 184, 48, fill="#FDF3F3", stroke=RED, r=8))
    b.append(text(830, 549, "DatabasePassword", 12, RED, "middle", "700"))
    b.append(f'<line x1="762" y1="549" x2="898" y2="549" stroke="{RED}" stroke-width="2"/>')
    b.append(text(830, 567, "does not exist: id-api is the login", 11, GREY, "middle"))

    # Monitoring
    b.append(icon("log-analytics", 1060, 230, 52, "Log Analytics", "AuditEvent: every\nSecretGet, by identity"))
    b.append(lines(990, 400, ["Audit answers: which identity", "read which secret, when,", "and whether it was throttled."], 11, GREY, 14))

    # Arrows
    b.append(arrow(400, 372, 400, 458, GREY, "1  token for id-api", 400, 420))
    b.append(arrow(630, 232, 718, 232, BLUE, "2  SecretGet\nBearer token", 674, 212))
    b.append(arrow(630, 300, 718, 455, BLUE, "3  SQL login\nBearer token", 690, 350))
    b.append(arrow(940, 232, 1030, 232, GREY, "audit", 985, 222, dash="4 3"))
    b.append(arrow(560, 372, 590, 458, GREY, "telemetry", 540, 440, dash="4 3"))
    # rotation runs along the top of the Azure box, outside the app
    b.append(f'<polyline points="272,135 830,135 830,146" fill="none" stroke="{AMBER}" stroke-width="2" stroke-dasharray="6 3" marker-end="url(#arrow-{AMBER[1:]})"/>')
    b.append(text(550, 128, "rotate: az keyvault secret set (measure/rotate.py)", 12, AMBER, "middle", "600"))

    return svg(W, H, "\n".join(b), "Key Vault with managed identity: the reference architecture")


# --------------------------------------------------------------- diagram 2
def secret_paths():
    W, H = 1200, 700
    b = []
    b.append(text(32, 64, "Four ways the same secret reaches one ASP.NET Core process, and what each one costs you.", 14, GREY))

    # App Service outer
    b.append(box(32, 90, 820, 580, fill="#F5F9FD", stroke="#C7E0F4", r=14))
    b.append(icon("app-service", 80, 124, 36))
    b.append(text(108, 130, "App Service instance", 14, BLUE, "start", "700"))
    b.append(icon("managed-identity", 790, 124, 36))
    b.append(text(770, 130, "id-api", 12, GREY, "end", "600"))

    # Platform row
    b.append(box(56, 150, 772, 96, fill="#EDF4FB", stroke="#C7E0F4", r=10))
    b.append(text(72, 174, "App Service platform (outside your process)", 12, BLUE, "start", "700"))
    b.append(badge(84, 210, 1))
    b.append(text(104, 206, "Key Vault reference resolver", 13, DARK, "start", "600"))
    b.append(text(104, 224, 'ExternalApi__KeyFromReference = @Microsoft.KeyVault(VaultName=kv;SecretName=ExternalApiKey)', 11, GREY))
    b.append(text(104, 238, "resolved with keyVaultReferenceIdentity before the process starts", 11, GREY))

    # Process box
    b.append(box(56, 270, 772, 380, fill=PANEL, stroke=LINE, r=10))
    b.append(text(72, 294, "dotnet process (ASP.NET Core 8)", 12, DARK, "start", "700"))

    # Endpoints (left)
    b.append(box(76, 320, 400, 310, fill=LIGHT, stroke=LINE, r=8))
    b.append(text(92, 344, "GET /api/secrets/status", 13, DARK, "start", "700"))
    b.append(text(92, 362, "fingerprint per path, never the value", 11, GREY))
    rows = [
        ("1 reference", "restart, refresh call, or 24 h", "0 per request", GREY),
        ("2 provider", "every ReloadInterval", "0 per request", GREY),
        ("3 cached", "every 60 s per instance", "1 per TTL window", GREEN),
        ("4 on demand", "immediately", "1 per request", RED),
    ]
    b.append(text(92, 392, "path", 11, GREY, "start", "700"))
    b.append(text(200, 392, "sees a rotated value", 11, GREY, "start", "700"))
    b.append(text(370, 392, "vault calls", 11, GREY, "start", "700"))
    b.append(f'<line x1="92" y1="398" x2="460" y2="398" stroke="{LINE}" stroke-width="1"/>')
    for i, (p, r, c, col) in enumerate(rows):
        y = 420 + i * 26
        b.append(text(92, y, p, 12, DARK, "start", "600"))
        b.append(text(200, y, r, 12, GREY))
        b.append(text(370, y, c, 12, col, "start", "700"))
    b.append(text(92, 548, "GET /api/orders", 13, DARK, "start", "700"))
    b.append(text(92, 566, "Authentication=Active Directory Default", 11, GREY))
    b.append(text(92, 582, "SqlClient asks Entra for a token for id-api.", 11, GREY))
    b.append(text(92, 598, "No secret is read, so no path applies.", 11, GREEN, "start", "600"))
    b.append(text(92, 616, "4,000 vault transactions per 10 s is the ceiling path 4 runs into.", 11, AMBER))

    # IConfiguration (right)
    b.append(box(510, 320, 300, 150, fill=LIGHT, stroke=LINE, r=8))
    b.append(icon("app-configuration", 542, 350, 36))
    b.append(text(566, 356, "IConfiguration", 13, DARK, "start", "700"))
    b.append(text(526, 392, 'ExternalApi:KeyFromReference', 11, GREY))
    b.append(text(526, 408, "  from environment, plain string", 11, GREY))
    b.append(badge(780, 436, 2))
    b.append(text(526, 436, 'ExternalApiKey', 11, GREY))
    b.append(text(526, 452, "  AddAzureKeyVault, ReloadInterval 5 min", 11, GREY))

    # SecretClient (right)
    b.append(box(510, 490, 300, 110, fill=LIGHT, stroke=LINE, r=8))
    b.append(text(526, 512, "SecretClient (Azure.Security.KeyVault.Secrets)", 12, DARK, "start", "700"))
    b.append(badge(526, 542, 3))
    b.append(text(546, 546, "behind IMemoryCache, 60 s TTL", 12, DARK))
    b.append(badge(526, 578, 4))
    b.append(text(546, 582, "GetSecretAsync on every request", 12, DARK))

    # Key Vault + SQL + audit on the far right
    b.append(icon("key-vault", 1010, 240, 72, "Azure Key Vault", "ExternalApiKey\nversion n, n+1, ..."))
    b.append(icon("sql-database", 1010, 600, 60, "Azure SQL", "contained user id-api, SID from client id"))
    b.append(icon("log-analytics", 1130, 420, 44, "AuditEvent", None))

    # arrows
    b.append(arrow(828, 198, 972, 232, BLUE, "SecretGet at start", 905, 205))
    b.append(arrow(810, 440, 972, 262, BLUE, "SecretGet every reload", 905, 370))
    b.append(arrow(810, 545, 972, 272, BLUE, "SecretGet per TTL\nor per request", 950, 480))
    b.append(arrow(476, 625, 972, 625, GREEN, "token, no password: SqlClient logs in as id-api", 720, 615))
    b.append(arrow(1040, 280, 1110, 392, GREY, None, dash="4 3"))
    b.append(arrow(660, 250, 660, 318, GREY, "environment variable", 730, 290))
    return svg(W, H, "\n".join(b), "Four ways a secret reaches your code (and one way it never has to)")


# --------------------------------------------------------------- diagram 3
def rotation_timeline(summary):
    """Seconds until each path served a rotated secret, over the measured runs
    in measure/rotation-summary.json, plus what each route did for the reference."""
    W, H = 1100, 560
    b = []
    b.append(text(32, 64, f"Measured {summary['measuredOn']} on {summary['app']}, polled every {summary['pollIntervalSeconds']} s; one dot per rotation run.", 13, GREY))
    runs = summary["runs"]
    x0, x1, maxs = 250, 700, 300
    rows = [("ondemand", "4 on demand"), ("cached", "3 cached (60 s TTL)"), ("provider", "2 provider (reload 5 min)")]
    for i, (key, label) in enumerate(rows):
        y = 120 + i * 70
        b.append(text(x0 - 16, y + 5, label, 14, DARK, "end", "600"))
        b.append(f'<line x1="{x0}" y1="{y}" x2="{x1}" y2="{y}" stroke="{LIGHT}" stroke-width="26"/>')
        vals = [r["seenSeconds"][key] for r in runs if r["seenSeconds"].get(key) is not None]
        if vals:
            lo, hi = min(vals), max(vals)
            xa = x0 + (x1 - x0) * lo / maxs
            xb = x0 + (x1 - x0) * hi / maxs
            b.append(f'<rect x="{xa}" y="{y - 6}" width="{max(4, xb - xa)}" height="12" fill="{BLUE}" opacity="0.25" rx="3"/>')
            for v in vals:
                cx = x0 + (x1 - x0) * v / maxs
                b.append(f'<circle cx="{cx}" cy="{y}" r="6" fill="{GREEN if v <= 60 else BLUE}"/>')
            b.append(text(xb + 14, y + 5, f"{lo} to {hi} s" if lo != hi else f"{lo} s", 13, DARK, "start", "700"))
    for t in (0, 60, 120, 180, 240, 300):
        x = x0 + (x1 - x0) * t / maxs
        b.append(f'<line x1="{x}" y1="{100}" x2="{x}" y2="{300}" stroke="{LINE}" stroke-width="0.5" stroke-dasharray="2 4"/>')
        b.append(text(x, 318, f"{t} s", 11, GREY, "middle"))
    b.append(text(760, 118, "Where the rotation falls inside the", 12, GREY))
    b.append(text(760, 134, "timer window decides the delay:", 12, GREY))
    b.append(text(760, 150, "the TTL and the reload interval are", 12, GREY))
    b.append(text(760, 166, "upper bounds, not typical values.", 12, GREY))

    # reference routes
    y = 370
    b.append(text(x0 - 16, y + 5, "1 reference", 14, DARK, "end", "600"))
    b.append(text(x0 - 16, y + 22, "App Service Key Vault reference", 11, GREY, "end"))
    routes = [(r["referenceRoute"]["route"], r["referenceRoute"]["seenSeconds"], r["referenceRoute"]["windowSeconds"]) for r in runs]
    for j, (route, seen, window) in enumerate(routes):
        yy = y + j * 34
        if seen is None:
            b.append(f'<rect x="{x0}" y="{yy - 11}" width="{x1 - x0}" height="22" fill="{RED}" opacity="0.12" rx="4"/>')
            b.append(text(x0 + 10, yy + 4, f"{route}: still the old value after {window // 60} min", 12, RED, "start", "600"))
        else:
            w = (x1 - x0) * seen / maxs
            b.append(f'<rect x="{x0}" y="{yy - 11}" width="{w}" height="22" fill="{GREEN}" rx="4"/>')
            b.append(text(x0 + w + 10, yy + 4, f"{route}: {seen} s", 12, GREEN, "start", "700"))
    b.append(text(x0, y + len(routes) * 34 + 8, "platform re-fetch: every 24 h (documented, not waited for)", 12, GREY))
    return svg(W, H, "\n".join(b), "Time until each path served the rotated secret")


if __name__ == "__main__":
    render("architecture", architecture(), 1200)
    render("secret-paths", secret_paths(), 1200)
    summary_file = HERE.parent / "measure" / "rotation-summary.json"
    if summary_file.exists():
        render("rotation-timeline", rotation_timeline(json.loads(summary_file.read_text(encoding="utf-8"))), 1100)
    else:
        print("no measure/rotation-summary.json, skipping rotation-timeline")
