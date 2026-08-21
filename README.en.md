# SSH Remote Control

[中文](README.md) · [English](README.en.md)

Agent skill + local CLI for **alias-first** SSH to Linux servers: key onboarding, layered diagnosis, pubkey/SFTP repair, scoped collaborator accounts, and (when requested) public-IP HTTPS.

Daily work after onboarding is native OpenSSH:

```bash
python scripts/sshctrl.py connect <host-or-alias>
ssh <alias> "whoami && hostname"
```

## Not this skill

- Ansible / Terraform / fleet provisioning
- Windows RDP
- Cloud-console-only access with no SSH path

## Install

```bash
pip install -r requirements.txt
python scripts/sshctrl.py --version
```

The CLI entry is only `scripts/sshctrl.py`. Sibling helpers live next to it as `sshctrl_*.py`. Do not add a copy at the skill root.

## Security notes

- Prefer `SSHCTRL_PASSWORD` with `-` as the password argument instead of putting the password on the command line.
- `repair-pubkey` for root sets `PermitRootLogin prohibit-password`.
- Host-key policy warns on unknown hosts instead of silently auto-adding.

See `SKILL.md` for the agent contract.
