# Collaborator Accounts

Use `server add-collaborator` when someone needs server access without sharing root or the admin alias. It creates a dedicated Linux account and opens **password-only login for that one user** via `Match User <username>`, leaving every other account's auth policy untouched.

```bash
python <skill-dir>/scripts/sshctrl.py server add-collaborator <admin-alias> <username> <tier> [options]
```

## Tiers

Pick based on what the collaborator actually needs. Ask if unclear.

| Tier | Grants | Key options |
| --- | --- | --- |
| `readonly-deploy` | Read/write on one project dir via group membership; no blanket sudo; optional passwordless restart of named services | `--group <existing-group>`, `--restart-service <name>` (repeatable) |
| `full-shell` | Ordinary user shell; never added to `sudo` / `wheel` / `docker` | none |
| `sudo-whitelist` | Only the exact absolute-path commands listed, via `/etc/sudoers.d/<user>` validated with `visudo -cf` | `--sudo-cmd <absolute-path-cmd>` (repeatable, required) |
| `sftp-only` | Chrooted to one directory via `ForceCommand internal-sftp`; no shell | `--chroot-dir <absolute-path>` (required) |

```bash
python <skill-dir>/scripts/sshctrl.py server add-collaborator prod-web alice readonly-deploy \
  --group deploy --restart-service myapp
python <skill-dir>/scripts/sshctrl.py server add-collaborator prod-web bob full-shell
python <skill-dir>/scripts/sshctrl.py server add-collaborator prod-web carol sudo-whitelist \
  --sudo-cmd "/usr/bin/docker restart myapp-container"
python <skill-dir>/scripts/sshctrl.py server add-collaborator prod-web dave sftp-only \
  --chroot-dir /srv/sftp/dave
```

## Contract

- Without `--password`, a random strong password is generated and printed once. Hand it over a secure channel immediately; nothing is persisted in plaintext.
- The new account cannot use key login (`PubkeyAuthentication no` in its `Match` block). That matches "password only, scoped, not root."
- `readonly-deploy`'s `--group` must already exist and already own the target directory (`chown -R :group dir && chmod -R 2775 dir`). The command only joins the group.
- Refuses to run if the username already exists or a `Match User <username>` block is already present.
- Verification is read-only (`sshd -T -C user=<username>`). It does not log in with the generated password.
- Usernames `root`, `admin`, `ubuntu`, `ec2-user`, `centos`, `debian` are rejected.
