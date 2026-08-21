# Long-Running Remote Tasks

SSH keepalives prevent idle firewall drops. They do not save a command if the TCP session dies. For work that may exceed ~2 minutes (build, migrate, large transfer), run it inside tmux on the server.

This skill's SSH config already sets `ServerAliveInterval 60`, `ServerAliveCountMax 3`, and `TCPKeepAlive yes`. That is layer 1. tmux is layer 2.

```bash
ssh <alias> "command -v tmux || (command -v apt-get >/dev/null && sudo apt-get install -y tmux) || (command -v yum >/dev/null && sudo yum install -y tmux)"

ssh <alias> "tmux new-session -d -s deploy 'cd /opt/app && ./deploy.sh'"
ssh <alias> "tmux capture-pane -t deploy -p | tail -50"
ssh <alias> -t "tmux attach -t deploy"
ssh <alias> "tmux ls"
ssh <alias> "tmux kill-session -t deploy"
```

Name sessions after the job (`deploy`, `build`, `migrate`), not `session1`. Prefer `capture-pane` over attaching unless the user needs an interactive TTY.

Do not reach for autossh, mosh, or Eternal Terminal for this workflow: they add ports or drop in-flight commands. Connection multiplexing (`ControlMaster`) speeds repeat SSH; it does not survive a dead master connection.
