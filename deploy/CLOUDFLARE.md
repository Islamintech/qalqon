# Putting qalqon-safe.uz behind Cloudflare

The panel renders private group messages, so the goal is not just "the domain
resolves" — it is that the origin is unreachable except through Cloudflare, the
sign-in audit log records real visitor IPs, and nothing about the dashboard is
ever cached at the edge.

Origin IP: `76.13.222.177`. Do the steps in order; DNS has to resolve before
the certificate work makes sense.

---

## 1. Add the zone

`.uz` cannot be registered at Cloudflare, so this is a nameserver change at your
existing registrar, not a transfer.

1. Cloudflare dashboard → **Add a site** → `qalqon-safe.uz` → Free plan.
2. Cloudflare shows two nameservers, e.g. `xxx.ns.cloudflare.com`.
3. At the registrar where you bought the domain, replace the existing
   nameservers with those two.

Propagation is usually minutes but the registrar may say up to 24h. Check:

```bash
dig +short NS qalqon-safe.uz
```

Wait until that returns the Cloudflare nameservers before continuing.

## 2. DNS records

Cloudflare's scan of a fresh `.uz` zone finds nothing, so all three records are
entered by hand. Cloudflare → **DNS** → **Add record**:

| Type | Name | Content | Proxy |
|---|---|---|---|
| A | `@` | `76.13.222.177` | **Proxied** (orange) |
| TXT | `@` | `v=spf1 -all` | — |
| TXT | `_dmarc` | `v=DMARC1; p=reject; sp=reject; adkim=s; aspf=s;` | — |

Enter TXT values without the surrounding quotes; Cloudflare adds them.

The domain sends no mail and has no MX record, so the two TXT records say
exactly that: `-all` authorizes no sender at all, and DMARC `p=reject` asks
receivers to drop anything claiming to be from `@qalqon-safe.uz`. A domain with
no SPF/DMARC is the easy one to spoof — these close that off. Do **not** add
`+a` to the SPF record: it would authorize whatever the apex A points at, which
is this dashboard's server.

No `www`. `WEB_BASE_URL`, `/setdomain` and the nginx `server_name` are all the
apex, so a `www` record would resolve to a host nginx does not answer for — it
would need either a second `server_name` or an edge redirect to be worth
having, and nothing points at it.

Verify the proxy is actually on — a proxied record resolves to Cloudflare's
range (104.x / 172.64.x), *not* to your origin:

```bash
dig +short qalqon-safe.uz     # expect Cloudflare IPs, NOT 76.13.222.177
```

If that returns the origin IP, the record is grey-clouded and every hardening
step below is doing nothing.

## 3. Origin certificate

Cloudflare → **SSL/TLS → Origin Server → Create Certificate**. Accept the
defaults (RSA, 15 years, hostnames `qalqon-safe.uz`). Cloudflare shows the
certificate and the private key **once** — copy both now.

On the server:

```bash
sudo mkdir -p /etc/ssl/cloudflare
sudo nano /etc/ssl/cloudflare/qalqon-safe.uz.pem   # paste the certificate
sudo nano /etc/ssl/cloudflare/qalqon-safe.uz.key   # paste the private key
sudo chmod 600 /etc/ssl/cloudflare/qalqon-safe.uz.key
sudo chown root:root /etc/ssl/cloudflare/*
```

This certificate is trusted by Cloudflare only, never by browsers. That is
correct — no browser connects to the origin directly.

## 4. SSL mode

Cloudflare → **SSL/TLS → Overview** → **Full (strict)**.

Not Flexible: Flexible makes Cloudflare talk to the origin over plain HTTP,
which would put session cookies and private messages in clear text across the
public internet. Not Full (non-strict) either: it encrypts but does not verify,
so it accepts any certificate and gives no protection against interception
between Cloudflare and the origin.

Then **SSL/TLS → Edge Certificates** → turn on **Always Use HTTPS**.

## 5. Real client IPs

```bash
sudo cp deploy/cloudflare-real-ip.conf /etc/nginx/conf.d/
```

Without this, `web/app.py` logs a Cloudflare edge address on every token
sign-in attempt, and the record of who tried to reach the dashboard is
worthless. Refresh it when Cloudflare changes ranges:

```bash
sudo deploy/refresh-cloudflare-ips.sh
```

## 6. Install the site

```bash
sudo cp deploy/nginx-qalqon.conf /etc/nginx/sites-available/qalqon
sudo ln -sf /etc/nginx/sites-available/qalqon /etc/nginx/sites-enabled/qalqon
sudo nginx -t && sudo systemctl reload nginx
```

`nginx -t` failing on `http2 on;` means nginx is older than 1.25 — replace that
line with `listen 443 ssl http2;` on the two listen lines instead.

## 7. Do not cache the dashboard

Cloudflare → **Caching → Cache Rules → Create rule**:

- Name: `qalqon — never cache`
- If: **Hostname** equals `qalqon-safe.uz`
- Then: **Bypass cache**

Every page is per-user and access-controlled. A cached authenticated response
served to the next visitor would hand one group's moderation records to
someone else — this rule is not an optimisation, it is part of the access
control.

## 8. Lock the origin to Cloudflare (after it works)

Only once `https://qalqon-safe.uz` loads and you can sign in.

**Authenticated Origin Pulls** — the origin refuses TLS from anyone not
presenting Cloudflare's client certificate:

```bash
sudo curl -fsS -o /etc/ssl/cloudflare/origin-pull-ca.pem \
  https://developers.cloudflare.com/ssl/static/authenticated_origin_pull_ca.pem
```

Uncomment the two `ssl_client_certificate` / `ssl_verify_client` lines in
`/etc/nginx/sites-available/qalqon`, then in Cloudflare → **SSL/TLS → Origin
Server** turn on **Authenticated Origin Pulls**. Reload nginx and reload the
panel in a browser. A `400 No required SSL certificate was sent` means the
Cloudflare-side toggle is off while nginx is enforcing — turn one on or the
other off, do not leave them mismatched.

Optionally also close the origin at the firewall so only Cloudflare can reach
443 at all:

```bash
for cidr in $(curl -fsS https://www.cloudflare.com/ips-v4); do
    sudo ufw allow proto tcp from "$cidr" to any port 443
done
sudo ufw deny 443
```

Check `sudo ufw status` before and after — if other sites (k-apply,
visa.k-apply.uz) are served from this same host, that `deny` closes them to the
public too. Skip the firewall step in that case; Authenticated Origin Pulls
alone already protects this site.

## 9. Finish the app side

```
# /opt/qalqon/.env
WEB_BASE_URL=https://qalqon-safe.uz
```

```bash
sudo systemctl restart qalqon-web qalqon
```

Both services: the bot builds its `/privacy` link from the same variable.

Then @BotFather → `/setdomain` → your bot → `qalqon-safe.uz`. The Telegram
login widget checks the page's host against this and silently refuses to render
otherwise.

## 10. Verify

```bash
dig +short qalqon-safe.uz                       # Cloudflare IPs
curl -sI https://qalqon-safe.uz | head -20      # 200, and a cf-cache-status of DYNAMIC/BYPASS
curl -s localhost:8080/healthz                  # {"ok":true}
```

Then in a browser: open `https://qalqon-safe.uz`, sign in with Telegram, and
confirm you land on the dashboard. Sign in once with a non-allow-listed account
and confirm it is refused — that check is the only thing between the internet
and your groups' private messages.

Finally, confirm the audit log sees you and not Cloudflare:

```bash
sudo journalctl -u qalqon-web -n 50 | grep 'token sign-in'
```

The address there must be your own public IP (`curl -s ifconfig.me`). If it is
a `104.` / `172.64.` address, step 5 did not take effect.
