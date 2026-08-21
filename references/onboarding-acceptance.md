# Onboarding Acceptance

A printed `server add` success is not the finish line. Treat the host as ready only after non-interactive key auth works.

## Order

1. Host key (`REMOTE HOST IDENTIFICATION HAS CHANGED` → confirm identity, then `ssh-keygen -R <host>`).
2. Auth path (`ssh -o BatchMode=yes`). A hang usually means SSH is waiting for a password or fingerprint prompt, not that the remote command is slow.
3. Server policy (`PubkeyAuthentication`, `PermitRootLogin`, `authorized_keys`). Reachable port does not mean key auth is allowed.
4. Only then run the real workload.

## After `server add`

```bash
python <skill-dir>/scripts/sshctrl.py server add <host> <user> <password> <alias> [--port N]
python <skill-dir>/scripts/sshctrl.py server diagnose <alias>
```

If BatchMode still fails:

```bash
python <skill-dir>/scripts/sshctrl.py server repair-pubkey <alias> <password>
```

## Done when all of these pass

```bash
ssh -o BatchMode=yes <alias> "echo ok"
ssh <alias> "whoami && hostname"
ssh <alias> "sshd -T | grep -i pubkeyauthentication"   # expect: pubkeyauthentication yes
```

Optional snapshot, not a substitute for the checks above:

```bash
ssh <alias> "date '+%F %T %Z' && uptime && free -h && df -h /"
```

Do not close the working session until a **new** BatchMode login succeeds.
