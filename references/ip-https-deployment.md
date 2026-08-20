# Public IP HTTPS Deployment

Use this procedure when a user requests HTTPS for a remotely managed application without a domain, or when adding TLS to a shared Nginx host. Treat it as a deployment change: preflight first, stage ACME validation, then issue and verify.

## Decision Gate

Use a publicly trusted IP certificate only when all conditions are true:

- The server has the requested public IPv4 or IPv6 address and its owner controls it.
- Public TCP 80 can serve ACME HTTP-01 validation and public TCP 443 can serve TLS.
- The ACME client supports IP identifiers and the required short-lived profile.
- Automatic renewal is acceptable and can be monitored.

For Let’s Encrypt, use Certbot 5.4 or newer with `--ip-address` and `--preferred-profile shortlived`. IP certificates are valid for about six days. Older distro Certbot packages commonly do not support this flow. Do not silently substitute a self-signed certificate: it encrypts traffic but produces browser warnings and does not meet a request for browser-trusted HTTPS.

If any gate fails, report the constraint and offer either a domain, a private CA/self-signed certificate for controlled clients, or an internal reverse proxy. Do not claim that a hostname certificate is valid for a bare IP.

## Preflight

Resolve the SSH alias first, then collect current state. Do not infer free capacity or a safe default TLS server.

```bash
python sshctrl.py connect <host>
ssh <alias> "nproc; free -h; df -h / /opt; ss -ltnp"
ssh <alias> "docker system df; docker ps --format '{{.Names}}\\t{{.Ports}}'"
ssh <alias> "nginx -T 2>/dev/null | grep -nE 'listen (80|443)|server_name|ssl_certificate'"
ssh <alias> "certbot --version 2>/dev/null || true"
```

Record the application port, the server block selected for the public IP on port 80, all existing 443 virtual hosts, and whether the host has a reusable ACME account. Keep account emails, cookies, private keys, and app secrets out of terminal output and source control.

For a Docker deployment, also inspect image/build space and persistent mounts. A service that caches downloads or logs can consume storage after a successful first start; do not assess capacity from image size alone.

## ACME Webroot on a Shared Nginx Host

Use webroot validation when Nginx already owns port 80. Do not stop a working web server merely to run Certbot standalone.

1. Back up the exact Nginx file that owns `server_name <public-ip>` on port 80.
2. Create a dedicated root, for example `/var/www/certbot/.well-known/acme-challenge/`.
3. Add this location before broad proxy and hidden-file rules in that same server block:

```nginx
location ^~ /.well-known/acme-challenge/ {
    root /var/www/certbot;
    default_type text/plain;
    try_files $uri =404;
}
```

`^~` is required when the host has a generic `location ~ /\\.` deny rule; otherwise `.well-known` can be rejected. After the edit, place a throwaway probe file under the webroot and verify it through the public-IP server block. Only then remove the probe.

```bash
ssh <alias> "nginx -t && systemctl reload nginx"
ssh <alias> "curl -i -H 'Host: <public-ip>' http://127.0.0.1/.well-known/acme-challenge/<probe>"
```

Also validate from outside the host before production issuance if possible.

### PowerShell Transport Rule

Do not embed Nginx variables such as `$uri`, `$host`, or `$remote_addr` inside a PowerShell double-quoted SSH command: PowerShell can expand them before SSH sees them, producing invalid or subtly broken Nginx configuration. For complete Nginx files and remote scripts, prefer a base64-encoded UTF-8 payload or transfer a reviewed file with `scp`; then write it remotely, run `nginx -t`, and reload only after the test succeeds. Always retain the explicit backup until verification passes.

## IP Certificate Issuance

Use a current pinned Certbot container when the host package is too old. Persist all Certbot state; the container is disposable but `/etc/letsencrypt`, `/var/lib/letsencrypt`, and `/var/log/letsencrypt` are not.

Run staging before production. A staging account may use no email only when that is intentional; reuse an existing production ACME account when available rather than exposing its contact details.

```bash
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v /var/log/letsencrypt:/var/log/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  certbot/certbot:v5.4.0 certonly --staging --non-interactive --agree-tos \
  --register-unsafely-without-email --preferred-profile shortlived \
  --webroot --webroot-path /var/www/certbot \
  --ip-address <public-ip> --cert-name <ip-cert-name>
```

After staging succeeds, repeat without `--staging`. When reusing an existing account, select it deliberately with `--account <account-id>` if needed. Do not use the `nginx` installer for IP certificates: current Certbot IP support issues certificates but does not install the Nginx configuration automatically.

## TLS Reverse Proxy and Certificate Selection

Create a dedicated 443 server block for the IP certificate. If direct IP clients may omit SNI, make this block the `default_server` for IPv4 and IPv6 only after confirming no other block is intentionally the default. Existing named domains continue to receive their own certificates through SNI.

```nginx
server {
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    server_name <public-ip>;

    ssl_certificate /etc/letsencrypt/live/<ip-cert-name>/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/<ip-cert-name>/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;

    location = /<app-prefix> { return 301 /<app-prefix>/; }
    location /<app-prefix>/ {
        proxy_pass http://127.0.0.1:<app-port>/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

The trailing slash in both `location` and `proxy_pass` deliberately strips the prefix. For example, `/media-parser/api/parse` becomes upstream `/api/parse`. Test the application’s URL behavior before choosing a prefix; an application that emits absolute asset paths may need a dedicated port or host instead.

Do not silently close an already-public application port. Offer to bind the upstream to loopback and force HTTPS as a separate, potentially breaking hardening change.

## Renewal Contract

Do not rely on generic Certbot output claiming that a scheduled task exists when Certbot ran in an ephemeral Docker container. Install a host-level service and timer (or equivalent monitored scheduler) that invokes the same image and persisted mounts at least twice daily, reloads Nginx only after a successful renewal command, and targets the IP certificate by name.

```bash
docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt \
  -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v /var/log/letsencrypt:/var/log/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  certbot/certbot:v5.4.0 renew --non-interactive --cert-name <ip-cert-name>
systemctl reload nginx
```

Install the scheduler, then run a scoped dry run:

```bash
<renew-script> --dry-run
systemctl list-timers <renew-timer> --no-pager
```

## Required Validation and Reporting

Validate all of the following before reporting success:

1. `nginx -t` passed before every reload and the intended listener is present.
2. The certificate contains `IP Address:<public-ip>` in SAN. The subject common name can be empty for an IP certificate.
3. `openssl s_client` without SNI and with IP SNI both present the IP certificate; each existing domain SNI still presents its domain certificate.
4. A client outside the server completes a normal HTTPS request without disabling certificate verification.
5. The reverse-proxied application root and one representative API request reach the upstream over HTTPS.
6. The renewal dry run succeeds and the host-level timer is active.

If an API returns a platform-specific 4xx/5xx response after the proxy delivers it, report that as an upstream application/platform issue, not a TLS failure. State separately whether HTTP was intentionally left exposed, the exact HTTPS URL/path, the certificate expiry, renewal cadence, and any remaining access-control risk.
