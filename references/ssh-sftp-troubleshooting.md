# SSH / SFTP Layered Troubleshooting

## Table of Contents

1. Purpose
2. Layered model
3. Evidence commands
4. Authentication repair
5. SFTP subsystem repair
6. Rescue versus production configuration
7. Common pitfalls
8. AI handoff prompt

## 1. Purpose

Use this reference when SSH, Codex remote access, Xftp, SFTP, scp, or rsync fails and the root cause is not obvious. The central rule is to classify the failure layer before changing server configuration.

## 2. Layered Model

```text
SSH / SFTP failure
├── Network layer
│   ├── wrong IP or DNS
│   ├── blocked port
│   ├── cloud security group or firewall
│   └── local proxy or network issue
├── Service listener layer
│   ├── sshd stopped
│   ├── wrong SSH port
│   └── Connection refused
├── Handshake layer
│   ├── banner or key-exchange issue
│   ├── host key mismatch
│   └── known_hosts conflict
├── Authentication layer
│   ├── wrong user
│   ├── wrong password
│   ├── PermitRootLogin blocks root password login
│   ├── PasswordAuthentication disabled
│   ├── PubkeyAuthentication disabled
│   ├── wrong client key
│   └── authorized_keys missing or has bad permissions
└── Subsystem layer
    ├── SSH login works but SFTP fails
    ├── Subsystem sftp missing
    ├── duplicate Subsystem sftp lines
    ├── wrong sftp-server path
    └── config changed but sshd was not reloaded
```

Important interpretation:

- `Handshake completed` means TCP and SSH handshake have likely passed; move to authentication diagnosis.
- `Permission denied` is normally authentication or account policy, not a network failure.
- `SFTP failed` does not prove SSH authentication failed. SFTP is an SSH subsystem and must be tested separately.

## 3. Evidence Commands

Start with the skill helper:

```bash
python sshctrl.py server diagnose <alias>
```

Manual local evidence:

```bash
ssh -G <alias> | grep -Ei 'hostname|user|port|identityfile'
ssh -vvv -o BatchMode=yes -o ConnectTimeout=10 <alias> "echo SSH_OK"
sftp -b - -oBatchMode=yes -oConnectTimeout=10 <alias>
```

For the SFTP batch probe, send `quit` on stdin.

Manual remote evidence after SSH works:

```bash
sshd -t
sshd -T | grep -Ei 'permitrootlogin|passwordauthentication|pubkeyauthentication|kbdinteractiveauthentication|usepam|authorizedkeysfile|subsystem'
grep -Rni '^[[:space:]]*Subsystem[[:space:]]\+sftp' /etc/ssh /etc/ssh/sshd_config.d 2>/dev/null
journalctl -u ssh -n 100 --no-pager || journalctl -u sshd -n 100 --no-pager
```

Common log mappings:

| Evidence | Likely cause |
| --- | --- |
| `Connection timed out` | Port, firewall, security group, route, or local network. |
| `Connection refused` | Host reachable, sshd not listening on that port. |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | known_hosts mismatch; verify identity before removing. |
| `Permission denied (publickey,password)` | No accepted authentication method. |
| `Permission denied (password)` after key attempts | Public key failed, client fell back to password. |
| `Authentication method not allowed` | Server policy does not allow the attempted method. |
| `subsystem request failed on channel 0` | SSH auth passed; SFTP subsystem did not start. |

## 4. Authentication Repair

Prefer the scripted repair when an alias exists:

```bash
python sshctrl.py server repair-pubkey <alias> <password>
```

Then verify:

```bash
ssh -o BatchMode=yes <alias> "whoami && hostname"
python sshctrl.py server diagnose <alias>
```

Manual checks:

```bash
ssh <alias> "sshd -T | grep -Ei 'pubkeyauthentication|authorizedkeysfile|permitrootlogin|passwordauthentication'"
ssh <alias> "ls -ld ~ ~/.ssh ~/.ssh/authorized_keys"
```

Expected server-side permissions:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
```

If root password login must be temporarily enabled from a rescue console:

```text
PermitRootLogin yes
PasswordAuthentication yes
KbdInteractiveAuthentication yes
UsePAM yes
```

Treat this as temporary. Switch back to key-only or deploy-user access after recovery.

## 5. SFTP Subsystem Repair

Use the scripted repair when SSH key login works but SFTP/Xftp fails:

```bash
python sshctrl.py server repair-sftp <alias>
```

The target stable line is:

```text
Subsystem sftp internal-sftp
```

Why prefer `internal-sftp`:

- It avoids distro-specific external `sftp-server` paths.
- It works well with restricted and chroot-style environments.
- It is simpler for automated repair.

Manual repair sequence:

```bash
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%Y%m%d-%H%M%S)
grep -vE '^[[:space:]]*Subsystem[[:space:]]+sftp([[:space:]]|$)' /etc/ssh/sshd_config > /tmp/sshd_config.new
printf '\nSubsystem sftp internal-sftp\n' >> /tmp/sshd_config.new
cat /tmp/sshd_config.new > /etc/ssh/sshd_config
sshd -t
systemctl reload sshd || systemctl reload ssh || systemctl restart sshd || systemctl restart ssh
```

If repair does not work, check includes:

```bash
grep -Rni '^[[:space:]]*Subsystem[[:space:]]\+sftp' /etc/ssh /etc/ssh/sshd_config.d 2>/dev/null
```

## 6. Rescue Versus Production Configuration

Rescue or onboarding state:

```text
PermitRootLogin yes
PasswordAuthentication yes
KbdInteractiveAuthentication yes
PubkeyAuthentication yes
UsePAM yes
Subsystem sftp internal-sftp
```

Production-leaning state:

```text
PermitRootLogin prohibit-password
PasswordAuthentication no
PubkeyAuthentication yes
UsePAM yes
Subsystem sftp internal-sftp
```

Preferred long-term model:

1. Create a `deploy` user.
2. Add the deploy user's public key.
3. Grant only needed project permissions.
4. Disable password login when key login is verified.
5. Avoid shared root passwords for collaborators.

## 7. Common Pitfalls

- Do not close the only working SSH/VNC session before testing a new login.
- Do not assume `sshd_config` text equals effective config; use `sshd -T`.
- Do not ignore `/etc/ssh/sshd_config.d/*.conf`; included snippets can override expectations.
- Do not use long nested PowerShell plus remote-shell one-liners for fragile repairs; upload a script or use the helper command.
- Do not treat Xftp/SFTP failures as proof that the password or key is wrong.
- Do not leave `PermitRootLogin yes` and `PasswordAuthentication yes` exposed longer than needed on public servers.

## 8. AI Handoff Prompt

Use this prompt when asking another agent to troubleshoot:

```text
Use $ssh-remote-control for this SSH/SFTP issue. First resolve the alias with sshctrl connect, then run sshctrl server diagnose. Classify the failure as network, listener, handshake, authentication, or SFTP subsystem before changing anything. If key auth fails, use repair-pubkey. If SSH works but SFTP/Xftp fails, use repair-sftp. Back up sshd_config, run sshd -t, reload/restart SSH, and verify a new SSH/SFTP connection before declaring success.
```
