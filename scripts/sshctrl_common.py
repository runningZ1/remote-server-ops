#!/usr/bin/env python3
import json
import os
import re
import subprocess
import sys

VERSION = "1.7.0"
CONFIG_DIR = os.path.expanduser("~/.ssh/sshctrl")
SERVERS_FILE = os.path.join(CONFIG_DIR, "servers.json")
RELOAD_SSHD = (
    "systemctl reload sshd || systemctl reload ssh "
    "|| systemctl restart sshd || systemctl restart ssh"
)


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_servers():
    if not os.path.exists(SERVERS_FILE):
        return {}
    with open(SERVERS_FILE) as f:
        return json.load(f)


def save_servers(servers):
    ensure_config_dir()
    with open(SERVERS_FILE, 'w') as f:
        json.dump(servers, f, indent=2)
    try:
        os.chmod(SERVERS_FILE, 0o600)
    except OSError:
        pass


def resolve_secret_password(value, label="密码"):
    """Positional password, '-' meaning env SSHCTRL_PASSWORD, or the env var alone."""
    if value == "-" or value is None or value == "":
        env = os.environ.get("SSHCTRL_PASSWORD")
        if env:
            return env
        if value == "-":
            print("✗ password 为 '-' 时必须设置环境变量 SSHCTRL_PASSWORD")
        else:
            print(f"✗ 未提供{label}。传入参数，或设置 SSHCTRL_PASSWORD")
        sys.exit(1)
    return value


def paramiko_client():
    """Load known_hosts and warn on unknown keys instead of silently auto-adding."""
    import paramiko
    ssh = paramiko.SSHClient()
    known = os.path.expanduser("~/.ssh/known_hosts")
    try:
        ssh.load_system_host_keys()
        if os.path.exists(known):
            ssh.load_host_keys(known)
    except Exception:
        pass
    ssh.set_missing_host_key_policy(paramiko.WarningPolicy())
    return ssh


def first_match_sshd_upsert_script(key, value):
    """sshd uses the first matching directive; only rewrite that first line."""
    return (
        f"if grep -qE '^[[:space:]]*{key}[[:space:]]' /etc/ssh/sshd_config; then "
        f"sed -i '0,/^[[:space:]]*{key}[[:space:]]/s/^[[:space:]]*{key}.*/{key} {value}/' /etc/ssh/sshd_config; "
        f"else echo '{key} {value}' >> /etc/ssh/sshd_config; fi"
    )


def run_ssh_command(alias, command, capture=True, timeout=30):
    """通过SSH在远程服务器上执行命令（免密方式）。"""
    try:
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=10', alias, command],
            capture_output=capture, text=True, timeout=timeout
        )
        return result
    except subprocess.TimeoutExpired:
        print(f"✗ 命令执行超时（{timeout}秒）")
        sys.exit(1)


def run_local_command(cmd, timeout=30):
    """执行本地命令并返回结果。"""
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def run_sftp_probe(alias, timeout=20):
    """用 batch 模式探测 SFTP 子系统是否能启动，避免进入交互等待。"""
    return subprocess.run(
        ['sftp', '-b', '-', '-oBatchMode=yes', '-oConnectTimeout=10', alias],
        input='quit\n', capture_output=True, text=True, timeout=timeout
    )


def _upsert_remote_sshd_config(ssh, key, value):
    """在远程 sshd_config 中更新或追加配置项（只改第一处，与 sshd 生效规则一致）。"""
    cmd = first_match_sshd_upsert_script(key, value)
    stdin, stdout, stderr = ssh.exec_command(cmd)
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        err = stderr.read().decode(errors='ignore').strip()
        raise RuntimeError(f"更新 {key} 失败: {err}")


def _print_command_output(title, result, max_lines=80):
    print(f"\n{title}")
    print("-" * len(title))
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    if not output:
        print("(无输出)")
        return
    lines = output.splitlines()
    for line in lines[:max_lines]:
        print(line)
    if len(lines) > max_lines:
        print(f"... 已截断 {len(lines) - max_lines} 行")


def validate_host(host):
    """验证主机名或IP地址格式。"""
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_pattern, host):
        parts = host.split('.')
        return all(0 <= int(part) <= 255 for part in parts)

    # 域名（宽松校验）
    domain_pattern = r'^[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}[a-zA-Z0-9]$'
    return re.match(domain_pattern, host) is not None
