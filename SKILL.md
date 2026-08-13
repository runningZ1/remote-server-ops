---
name: ssh-remote-control
description: >-
  Configure, diagnose, repair, and use SSH remote access through stable local
  aliases. Use when Codex needs to connect to remote Linux servers, set up SSH
  key authentication, resolve host-to-alias mappings, run remote commands,
  transfer files with ssh/scp/rsync/sftp, repair public-key authentication,
  diagnose SSH handshake/authentication failures, fix SFTP subsystem errors
  such as "subsystem request failed" and "Unable to start subsystem: sftp",
  or create a scoped non-root collaborator account with password-only login.
---

# SSH Remote Control

Use this skill to operate remote servers through native SSH after resolving a stable local alias. Keep the workflow alias-first: resolve or create the alias, then use `ssh <alias> "..."`, `rsync`, `scp`, or `sftp`.

## Core Rules

1. Resolve aliases before remote work:

```bash
python sshctrl.py connect <host-or-alias-fragment>
```

2. Use the alias returned by `USING_ALIAS=<alias>` for all daily operations:

```bash
ssh <alias> "whoami && hostname"
rsync -avz --progress local_dir/ <alias>:/remote/path/
scp local_file.txt <alias>:/remote/path/
```

3. Avoid password-based remote execution paths after onboarding. Do not use `sshpass`, ad hoc Paramiko scripts, heredoc password automation, or direct `ssh user@ip` when a configured alias exists.

4. Treat `root + password` as a rescue or onboarding state, not the final production posture. Prefer key auth and, for long-lived systems, a deploy user with scoped permissions.

5. Before changing SSH server configuration, back it up, run `sshd -t`, reload/restart SSH, and verify from a new connection before closing any working session.

6. Never invent an alias for a brand-new server. `server add`'s `alias` argument is required precisely so this cannot be skipped silently. Ask the user what they want to call it before running `server add` — do not default to an IP-derived name on your own judgment. See "New Server Onboarding" for the question to ask and the fallback order.

## Standard Workflow

### Existing Server

```bash
python sshctrl.py connect <host>
```

Handle outputs:

| Output | Action |
| --- | --- |
| `USING_ALIAS=<alias>` | Use `ssh <alias> "..."` for work. |
| `AUTH_FAILED:<alias>:<reason>` | Run `python sshctrl.py server diagnose <alias>`, then repair as needed. |
| `NO_ALIAS:<target>` | Ask for username/password and run `server add`. |

### New Server Onboarding

Use this once when the user provides host, username, password, and optional port:

```bash
python sshctrl.py server add <host> <username> <password> <alias> [--port <port>]
```

`alias` is a required argument, and that is deliberate: do not pick one yourself and run
`server add` before asking. Before the first `server add` for a server that has no
existing alias, ask the user what they want to call it. Suggest, in order:

1. The project or app this server hosts (e.g. `payments-api`, `blog-prod`)
2. The cloud vendor plus a short qualifier (e.g. `aliyun-hk`, `vultr-tokyo`)
3. Only if the user has no preference for either: the IP address itself

Do not silently derive an alias from the IP (e.g. `156_239_227_141`) as a default —
that used to be the tool's own fallback and produces aliases nobody can recognize later
when they have several servers configured. Ask, then pass whatever the user picks.

The command tests password SSH, generates or reuses a key, uploads the public key, writes `~/.ssh/config`, and verifies key login.

The password is a plain positional CLI argument (visible in shell history and process
listings for the duration of the call). This is an accepted tradeoff for local,
interactive onboarding of a single server — it is the one place in this skill's workflow
where a password legitimately appears on the command line. It must not be reused as a
pattern for daily operations; rule 3 (avoid `sshpass`/password automation) applies to
everything after onboarding.

### Daily Remote Work

```bash
ssh <alias> "docker ps"
ssh <alias> "cd /opt/app && git status --short"
rsync -avz --partial --progress local_dir/ <alias>:/remote/path/
sftp <alias>
```

Keep remote commands simple in PowerShell. For complex remote logic, upload a script and run it remotely instead of nesting long quoted one-liners.

## Command Reference

```bash
# Find alias without connecting
python sshctrl.py find <host-or-fragment>

# Resolve alias and verify non-interactive key auth
python sshctrl.py connect <host-or-fragment>

# Add a new server (alias is required — ask the user first, see New Server Onboarding)
python sshctrl.py server add <host> <username> <password> <alias> [--port <port>]

# List or remove configured servers
python sshctrl.py server list
python sshctrl.py server remove <alias>

# Execute through helper, though direct ssh <alias> is preferred
python sshctrl.py server ssh <alias> ["command"]

# Repair public-key authentication when key login fails
python sshctrl.py server repair-pubkey <alias> <password>

# Read-only layered diagnosis for SSH auth and SFTP subsystem
python sshctrl.py server diagnose <alias> [--full]

# Repair SFTP subsystem to internal-sftp and verify it
python sshctrl.py server repair-sftp <alias>

# Create a scoped, password-only collaborator account (never root)
python sshctrl.py server add-collaborator <alias> <username> <tier> [options]
```

## Diagnosis Routing

Use `server diagnose` before guessing. It checks local SSH config, BatchMode SSH auth, effective remote `sshd -T` policy, SFTP subsystem config, and SFTP startup.

```bash
python sshctrl.py server diagnose <alias>
```

Route by symptom:

| Symptom | Meaning | Next step |
| --- | --- | --- |
| `Handshake completed` then auth failure | Network and port are likely OK; auth layer failed. | Check user, key, password policy, `PermitRootLogin`, `PasswordAuthentication`, `authorized_keys`. |
| `Permission denied (password)` after key attempt | Public key not accepted or server policy rejects it. | `python sshctrl.py server repair-pubkey <alias> <password>` |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | Known-host key mismatch. | Confirm server identity, then `ssh-keygen -R <host>`. |
| `subsystem request failed on channel 0` | SSH auth may work, SFTP subsystem failed. | `python sshctrl.py server repair-sftp <alias>` |
| `Unable to start subsystem: sftp` | SFTP config missing, duplicated, or wrong path. | Diagnose and repair SFTP subsystem. |
| `server add` step 1 fails with `AuthenticationException` (no alias exists yet) | No SSH access at all yet, so `diagnose`/`repair-*` cannot run (they need working SSH). Root cause is almost always server-side policy, not a wrong password. | `server add` now auto-prints a one-shot VNC/console rescue script (`build_vnc_auth_rescue_script`) covering `PasswordAuthentication`, `AllowUsers`/`AllowGroups`, `PermitRootLogin`, and missing `Subsystem sftp` in one pass — paste it into the provider's VNC console, not SSH. |

For detailed SSH/SFTP troubleshooting, read `references/ssh-sftp-troubleshooting.md`.

### Pre-alias auth failures (no working SSH yet)

If `server add` fails at step 1 with an authentication error, the server is unreachable
by any of this tool's SSH-based commands — `diagnose` and `repair-*` all require SSH to
already work. Do not iterate one setting at a time by asking the user to screenshot VNC
output repeatedly; that wastes multiple round-trips. Instead, `server add`'s failure
message already includes a single consolidated script for the provider's VNC/console
covering the four most common blockers found in practice (2026-07-11 incident):
`PasswordAuthentication no` (sometimes on an earlier line that wins over a later `yes`),
`AllowUsers` missing the target user, `PermitRootLogin no`, and a completely absent
`Subsystem sftp` line (breaks pubkey upload even after auth succeeds). Have the user run
it once, then retry `server add`.

## Repair Policy

### Public-Key Auth

Use `repair-pubkey` when an alias exists but non-interactive key auth fails:

```bash
python sshctrl.py server repair-pubkey <alias> <password>
ssh -o BatchMode=yes <alias> "whoami && hostname"
```

This command uses the password only for the repair session.

**Trap: `repair-pubkey` silently disables root password login.** To make root's public-key
auth work, it sets `PermitRootLogin prohibit-password` (old name: `without-password`). That
value is root-specific and blocks root's *password* login even while
`PasswordAuthentication` stays `yes` globally — `sshd -T` output alone makes it look like
password auth is still open for everyone, but root will get
`Permission denied (publickey,password)` on a password attempt (confirmed twice in
practice, 2026-07-11 and independently again 2026-08-12). `repair-pubkey` now prints a
warning when this applies. If a user explicitly wants root reachable by *both* key and
password, don't rely on `repair-pubkey` for that — back up `sshd_config`, set
`PermitRootLogin yes` deliberately, `sshd -t`, reload, and tell the user this widens the
attack surface (brute-force risk) and that a scoped non-root account (see "Collaborator
Accounts" below) is usually the safer fit for what they actually want.

### SFTP Subsystem

Use `repair-sftp` only after SSH key login works:

```bash
python sshctrl.py server repair-sftp <alias>
```

The command backs up `/etc/ssh/sshd_config`, removes duplicate `Subsystem sftp` entries from the main config, appends `Subsystem sftp internal-sftp`, runs `sshd -t`, reloads/restarts SSH, and verifies SFTP in batch mode.

If it still fails, inspect `/etc/ssh/sshd_config.d/*.conf` and service logs:

```bash
ssh <alias> "grep -Rni '^[[:space:]]*Subsystem[[:space:]]\\+sftp' /etc/ssh /etc/ssh/sshd_config.d 2>/dev/null"
ssh <alias> "journalctl -u ssh -n 100 --no-pager || journalctl -u sshd -n 100 --no-pager"
```

## Collaborator Accounts (Least Privilege, Never Root)

When a user wants to give a collaborator server access without sharing root, use
`server add-collaborator` instead of handing out the admin alias or opening root password
auth. It creates a dedicated Linux account scoped to one of four tiers, and — critically —
opens **password-only login for that one account** via an sshd `Match User <username>`
block, leaving root and every other account's auth policy untouched.

```bash
python sshctrl.py server add-collaborator <admin-alias> <username> <tier> [options]
```

Tiers (pick based on what the collaborator actually needs to do — ask if unclear):

| Tier | Grants | Key options |
| --- | --- | --- |
| `readonly-deploy` | Read/write on one project dir via group membership; no blanket sudo; optional passwordless restart of named services | `--group <existing-group>`, `--restart-service <name>` (repeatable) |
| `full-shell` | Ordinary user shell; explicitly never added to `sudo`/`wheel`/`docker` | none |
| `sudo-whitelist` | No shell-wide sudo; only the exact absolute-path commands listed, via `/etc/sudoers.d/<user>` validated with `visudo -cf` | `--sudo-cmd <absolute-path-cmd>` (repeatable, required) |
| `sftp-only` | Chrooted to one directory via `ForceCommand internal-sftp`; no shell at all | `--chroot-dir <absolute-path>` (required) |

```bash
python sshctrl.py server add-collaborator prod-web alice readonly-deploy \
  --group deploy --restart-service myapp
python sshctrl.py server add-collaborator prod-web bob full-shell
python sshctrl.py server add-collaborator prod-web carol sudo-whitelist \
  --sudo-cmd "/usr/bin/docker restart myapp-container"
python sshctrl.py server add-collaborator prod-web dave sftp-only \
  --chroot-dir /srv/sftp/dave
```

Notes:

- Without `--password`, a random strong password is generated and printed exactly once —
  hand it to the collaborator over a secure channel immediately; nothing is persisted to
  disk in plaintext.
- The new account cannot use key-based login (`PubkeyAuthentication no` in its own `Match`
  block) — this is deliberate, matching the common ask of "password only, scoped, not
  root," not an oversight to "fix" later.
- `readonly-deploy`'s `--group` must already exist and already own the target directory
  (typically `chown -R :group dir && chmod -R 2775 dir`); the command only joins the user
  to the group, it does not touch directory ownership.
- Refuses to run if the username already exists or a `Match User <username>` block is
  already present, rather than silently overwriting existing config.
- Verification is read-only (`sshd -T -C user=<username>`) — it does not attempt to log in
  with the generated password, consistent with rule 3 (no `sshpass`/password automation).

## Resource Navigation

- Read `references/ssh-sftp-troubleshooting.md` for the full layered model, rescue-vs-production configs, evidence commands, and AI handoff prompt.
- Read `references/ssh-commands-reference.md` for broader SSH/scp/rsync command examples.
- Read `references/detailed-guide.md` when onboarding a new user to the older full workflow.
- Treat files in `references/legacy/` as historical context only; do not load them unless investigating previous behavior.

## Validation

After changing this skill or its scripts, run:

```bash
python -m py_compile sshctrl.py
python sshctrl.py --version
python sshctrl.py server --help
python sshctrl.py server diagnose --help
python sshctrl.py server repair-sftp --help
python sshctrl.py server add-collaborator --help
```

If the system skill-creator tools are available, also run:

```bash
python C:\Users\zijie\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\zijie\.agents\skills\ssh-remote-control
```
