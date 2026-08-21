---
name: remote-server-ops
description: >-
  Operate remote Linux servers through stable SSH aliases: onboard key auth,
  diagnose and repair SSH/SFTP, run daily ssh/rsync/sftp, add scoped
  collaborators, deploy via GitHub deploy keys, and set up HTTPS/TLS
  (including a publicly trusted cert for a bare public IP). Use when connecting
  to a VPS, fixing Permission denied or SFTP subsystem errors, or doing
  host-level ops on a remotely managed Linux machine. Do not use for
  Ansible/Terraform fleets, Windows RDP, or cloud-console-only work.
---

# Remote Server Ops

Alias-first remote Linux operations. The only CLI is `scripts/sshctrl.py`. Resolve this skill directory; it is not on `PATH`.

```bash
python <skill-dir>/scripts/sshctrl.py connect <host-or-alias-fragment>
ssh <alias> "whoami && hostname"
```

## Rules

1. Resolve or create the alias before remote work. Never invent an alias — ask (project name, then cloud qualifier, IP last).
2. After onboarding: no `sshpass`, Paramiko password sessions, or `ssh user@ip` when an alias exists.
3. `root + password` is rescue/onboarding, not production.
4. Before changing sshd: backup, `sshd -t`, reload, verify a **new** session before closing the working one.
5. On PowerShell, keep remote commands simple; never embed `$uri`/`$host`/`$remote_addr` in double-quoted SSH strings.
6. For `server add` / `repair-pubkey`, prefer `SSHCTRL_PASSWORD` with password argument `-`.

## Workflow

| `connect` output | Action |
| --- | --- |
| `USING_ALIAS=<alias>` | Native `ssh`/`rsync`/`sftp` |
| `AUTH_FAILED:<alias>:<reason>` | `sshctrl server diagnose <alias>`, then repair |
| `NO_ALIAS:<target>` | Ask user/password/alias → `sshctrl server add <host> <user> <password> <alias> [--port N]` |

Jobs > ~2 minutes: `references/long-running-tasks.md`.

```bash
sshctrl find <host-or-fragment>
sshctrl server list | remove <alias>
sshctrl server repair-pubkey <alias> <password>
sshctrl server diagnose <alias> [--full]
sshctrl server repair-sftp <alias>
sshctrl server add-collaborator <alias> <user> <tier> [options]
```

## Diagnosis

Diagnose before guessing. `sshd` honors the **first** matching directive; `/etc/ssh/sshd_config.d/` can still win.

| Symptom | Next |
| --- | --- |
| Auth failure after handshake | user/key/policy/`authorized_keys` |
| `Permission denied (password)` after key | `repair-pubkey` |
| Host identification changed | confirm identity, `ssh-keygen -R <host>` |
| SFTP subsystem failed | `repair-sftp` (needs working SSH) |
| `server add` step 1 `AuthenticationException` | paste the printed VNC rescue script once, retry |

**Trap:** `repair-pubkey` for root sets `PermitRootLogin prohibit-password`. Full layer model: `references/ssh-sftp-troubleshooting.md`.

## Deferred reading

After `server add`, accept the host only with `references/onboarding-acceptance.md`. Collaborators → `references/collaborator-accounts.md`. HTTPS → `references/ip-https-deployment.md` before Nginx/Certbot. GitHub deploy-key → `references/github-deploy-guide.md` only when that is the job. Extra ssh/rsync → `references/ssh-commands-reference.md`.

Validate with `python -m py_compile scripts/sshctrl.py` and `python scripts/sshctrl.py --version`.
