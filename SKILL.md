---
name: ssh-remote-control
description: >-
  Configure, diagnose, repair, and use SSH remote access through stable local
  aliases. Use when Codex needs to connect to remote Linux servers, set up SSH
  key authentication, resolve host-to-alias mappings, run remote commands,
  transfer files with ssh/scp/rsync/sftp, repair public-key authentication,
  diagnose SSH handshake/authentication failures, or fix SFTP subsystem errors
  such as "subsystem request failed" and "Unable to start subsystem: sftp".
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
python sshctrl.py server add <host> <username> <password> [alias] [--port <port>]
```

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

# Add a new server
python sshctrl.py server add <host> <username> <password> [alias] [--port <port>]

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
```

If the system skill-creator tools are available, also run:

```bash
python C:\Users\zijie\.codex\skills\.system\skill-creator\scripts\quick_validate.py C:\Users\zijie\.agents\skills\ssh-remote-control
```
