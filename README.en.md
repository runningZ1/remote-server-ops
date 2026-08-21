# Remote Server Ops

[![GitHub stars](https://img.shields.io/github/stars/runningZ1/remote-server-ops?style=flat-square)](https://github.com/runningZ1/remote-server-ops/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/runningZ1/remote-server-ops?style=flat-square)](https://github.com/runningZ1/remote-server-ops/commits/master)
[![Open issues](https://img.shields.io/github/issues/runningZ1/remote-server-ops?style=flat-square)](https://github.com/runningZ1/remote-server-ops/issues)

[中文](README.md) · [English](README.en.md)

**Alias-first remote Linux operations for people and AI agents.** Turn one-time password onboarding into reusable, auditable OpenSSH aliases, then use native `ssh`, `scp`, `rsync`, and `sftp` for daily work. The CLI also covers SSH/SFTP diagnosis, public-key repair, scoped collaborator accounts, GitHub Deploy Key deployment, and trusted HTTPS for a public IP.

> [!IMPORTANT]
> This is not another SSH client. It is for safely bringing an unfamiliar server into a local workflow without returning to passwords and raw IP addresses for routine work.

> [!NOTE]
> This project was formerly named `ssh-remote-control` and is now `remote-server-ops`. Old GitHub links redirect automatically.

## Contents

- [When to use it](#when-to-use-it)
- [What it does](#what-it-does)
- [Quick start](#quick-start)
- [Daily workflow](#daily-workflow)
- [Command reference](#command-reference)
- [Security model](#security-model)
- [Troubleshooting](#troubleshooting)
- [Using it with an AI agent](#using-it-with-an-ai-agent)
- [Further reading](#further-reading)
- [Contributing](#contributing)

## When to use it

Use this project to:

- onboard a VPS, cloud VM, or self-managed Linux host with stable SSH key authentication;
- resolve an IP, hostname, or project fragment to an alias in local `~/.ssh/config`;
- diagnose `Permission denied`, host-key changes, handshake failures, or SFTP subsystem errors;
- create scoped accounts for collaborators without sharing root credentials, admin keys, or an admin alias;
- deploy a private GitHub repository with a Deploy Key, or configure trusted HTTPS for a bare public IP;
- give an agent a safe workflow that resolves the host and its boundaries before remote execution.

It is not an Ansible/Terraform fleet orchestrator, a Windows RDP tool, or a substitute for cloud-console access where no SSH path exists.

## What it does

| Capability | Problem solved | Entry point |
| --- | --- | --- |
| Alias lookup and verification | Avoid guessing SSH configuration or bypassing an existing alias with a raw IP | `connect`, `find` |
| Secure onboarding | Use a password once to establish key authentication and a local alias | `server add` |
| Layered diagnosis | Separate network, listener, handshake, authentication, and SFTP subsystem failures | `server diagnose` |
| Targeted repair | Repair public-key auth or SFTP and verify the result | `repair-pubkey`, `repair-sftp` |
| Least-privilege collaboration | Create individual Linux accounts with role-scoped access | `add-collaborator` |
| Deployment and HTTPS guidance | Use constrained procedures for Deploy Keys, long jobs, Nginx, and ACME | `references/` |

## Quick start

### 1. Install prerequisites

Install Python 3, `pip`, and the system OpenSSH client (`ssh`). From the repository root:

```bash
python -m pip install -r requirements.txt
python scripts/sshctrl.py --version
```

`scripts/sshctrl.py` is the only CLI entry point. The `scripts/sshctrl_*.py` files are internal modules; do not invoke them directly or copy them to the repository root.

### 2. Existing alias: resolve and verify it

```bash
python scripts/sshctrl.py connect <IP, hostname, alias, or alias fragment>
ssh <alias> "whoami && hostname"
```

`connect` determines the next action:

| Output | Next step |
| --- | --- |
| `USING_ALIAS=<alias>` | Use native `ssh` / `scp` / `rsync` / `sftp` with that alias. |
| `AUTH_FAILED:<alias>:<reason>` | Run `server diagnose` before attempting a repair. |
| `NO_ALIAS:<target>` | Confirm the host, login user, and meaningful alias, then onboard it. |

### 3. New host: onboard once, use the alias thereafter

Set `SSHCTRL_PASSWORD` safely in the current shell, then pass `-` instead of a password argument:

```bash
python scripts/sshctrl.py server add <host> <user> - <alias> [--port N]
python scripts/sshctrl.py server diagnose <alias>
ssh -o BatchMode=yes <alias> "echo SSH_OK"
```

Choose stable, meaningful names such as `blog-prod` or `api-aws`, rather than an opaque IP address. A host is onboarded only after a new non-interactive key-auth session succeeds. See the full [onboarding acceptance](references/onboarding-acceptance.md) contract.

## Daily workflow

```text
Resolve target → verify non-interactive key auth → work through native OpenSSH → verify changes in a new session
```

```bash
# Run a remote command
ssh <alias> "uptime && df -h /"

# Upload, synchronize, or use SFTP
scp ./release.tar.gz <alias>:/opt/releases/
rsync -avz --progress ./dist/ <alias>:/var/www/app/
sftp <alias>
```

Run builds, migrations, and large transfers expected to take more than about two minutes inside server-side `tmux`. SSH keepalives reduce idle disconnects; they do not preserve a command after a broken TCP session. See [long-running tasks](references/long-running-tasks.md).

## Command reference

| Task | Command |
| --- | --- |
| Find a local alias without connecting | `python scripts/sshctrl.py find <target>` |
| Resolve an alias and verify key auth | `python scripts/sshctrl.py connect <target>` |
| Onboard a new host | `python scripts/sshctrl.py server add <host> <user> - <alias> [--port N]` |
| List or remove managed hosts | `python scripts/sshctrl.py server list` / `server remove <alias>` |
| Run a command through an alias | `python scripts/sshctrl.py server ssh <alias> "uptime"` |
| Read-only SSH/SFTP diagnosis | `python scripts/sshctrl.py server diagnose <alias> [--full]` |
| Repair public-key authentication | `python scripts/sshctrl.py server repair-pubkey <alias> -` |
| Repair the SFTP subsystem | `python scripts/sshctrl.py server repair-sftp <alias>` |
| Create a scoped collaborator | `python scripts/sshctrl.py server add-collaborator <alias> <user> <tier> [options]` |

Run `python scripts/sshctrl.py --help` for complete arguments.

### Collaborator tiers

| Tier | Access boundary | Key options |
| --- | --- | --- |
| `readonly-deploy` | Read/write through one project group; no blanket sudo; optional restart of named services | `--group`, `--restart-service` |
| `full-shell` | Ordinary shell; never added to `sudo`, `wheel`, or `docker` | none |
| `sudo-whitelist` | Passwordless execution of only explicitly listed absolute-path commands | `--sudo-cmd` (required, repeatable) |
| `sftp-only` | Chrooted directory, SFTP only, no shell | `--chroot-dir` (required) |

Examples and the account contract are in [collaborator accounts](references/collaborator-accounts.md).

## Security model

This project deliberately enforces these boundaries:

- **Aliases first.** When an alias exists, routine work does not use `ssh user@ip`, `sshpass`, or password-based Paramiko sessions.
- **Passwords are for onboarding or rescue only.** `server add` and `repair-pubkey` accept `-` to read `SSHCTRL_PASSWORD` instead of exposing a password in argv. Set it briefly in the current shell and clear it promptly.
- **Evidence before change.** Use `diagnose` to classify the failure layer; do not conflate network, authentication, and SFTP failures.
- **SSH configuration changes are reversible.** Back up `sshd`, run `sshd -t`, reload it, and test a new session before closing the working one.
- **Root is not a routine login model.** `repair-pubkey` sets `PermitRootLogin prohibit-password` for root. Prefer a non-root administrator and least-privilege collaborator accounts in production.
- **Unknown host keys are not silently trusted.** Verify server identity before changing `known_hosts`; never suppress the warning merely to make a command succeed.

## Troubleshooting

| Symptom | First action |
| --- | --- |
| `Permission denied` | Run `python scripts/sshctrl.py server diagnose <alias>` and inspect user, key, server policy, and `authorized_keys`. |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | Verify the server identity out of band, then update the local record with `ssh-keygen -R <host>` if appropriate. |
| SSH works but SFTP/Xftp fails | Run `server repair-sftp`; this is not automatically an SSH-authentication failure. |
| Password prompt remains after onboarding | Run `server diagnose`, then `repair-pubkey` if needed; verify again with `BatchMode=yes`. |
| A remote build disconnects | Move it into `tmux` and read progress with `capture-pane`. |

For evidence commands, failure layers, and repair limits, read [SSH / SFTP layered troubleshooting](references/ssh-sftp-troubleshooting.md).

## Using it with an AI agent

When the agent runtime can load this skill, use:

```text
Use $remote-server-ops to resolve the alias before operating on a remote Linux server.
```

The agent contract lives in [SKILL.md](SKILL.md): resolve aliases first, diagnose before repair, verify every `sshd` change in a new session, and never place passwords or private keys in logs.

## Further reading

| Scenario | Document |
| --- | --- |
| Acceptance after onboarding | [onboarding-acceptance.md](references/onboarding-acceptance.md) |
| Layered SSH / SFTP diagnosis and repair | [ssh-sftp-troubleshooting.md](references/ssh-sftp-troubleshooting.md) |
| Remote commands, tunnels, transfers, and rsync | [ssh-commands-reference.md](references/ssh-commands-reference.md) |
| Builds, migrations, and other long jobs | [long-running-tasks.md](references/long-running-tasks.md) |
| Least-privilege collaborator accounts | [collaborator-accounts.md](references/collaborator-accounts.md) |
| Deploying a private GitHub repository with Deploy Keys | [github-deploy-guide.md](references/github-deploy-guide.md) |
| Trusted HTTPS for a bare public IP | [ip-https-deployment.md](references/ip-https-deployment.md) |

## Contributing

Bug reports, distribution-specific notes, documentation improvements, and small focused pull requests are welcome. Before submitting, run:

```bash
python -m py_compile scripts/sshctrl.py scripts/sshctrl_alias.py scripts/sshctrl_collaborator.py scripts/sshctrl_common.py scripts/sshctrl_onboard.py scripts/sshctrl_repair.py
python scripts/sshctrl.py --help
git diff --check
```

Remove passwords, private keys, cookies, sensitive IP addresses, and the full contents of `~/.ssh/config` from reports. A redacted command, actual output, expected result, OS, and OpenSSH/Python versions are enough to make most reports actionable.

## License and support

> [!CAUTION]
> This repository does not currently include a `LICENSE` file. Public visibility does not grant permission to reuse, modify, or distribute the code; do not assume an open-source license until one is explicitly added.

If this project improves a server workflow or an agent workflow, consider starring the repository and opening an issue with a real-world scenario, failure case, or documentation improvement. Those reports directly help it become a more reliable open-source tool.
