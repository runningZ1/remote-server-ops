#!/usr/bin/env python3
"""
SSH Remote Control - 核心CLI

用途：建立与远程服务器的SSH免密验证连接。

初始配置完成后，日常操作直接使用：
    ssh <别名> "命令"
    scp <别名>:

用法:
    sshctrl server add <host> <用户名> <密码> [别名] [--port 端口]  # 配置服务器SSH免密
    sshctrl server list                              # 列出已配置服务器
    sshctrl server remove <别名>                     # 移除服务器配置
    sshctrl server ssh <别名> [命令]                 # SSH连接/执行
"""

import argparse
import sys
import os
import json
import subprocess
import platform
import re
import time
import string
import secrets

VERSION = "1.3.0"

CONFIG_DIR = os.path.expanduser("~/.ssh/sshctrl")
SERVERS_FILE = os.path.join(CONFIG_DIR, "servers.json")


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


def _upsert_remote_sshd_config(ssh, key, value):
    """在远程 sshd_config 中更新或追加配置项。"""
    cmd = (
        f"grep -qE '^[[:space:]]*{key}' /etc/ssh/sshd_config "
        f"&& sed -i 's|^[[:space:]]*{key}.*|{key} {value}|' /etc/ssh/sshd_config "
        f"|| echo '{key} {value}' >> /etc/ssh/sshd_config"
    )
    stdin, stdout, stderr = ssh.exec_command(cmd)
    rc = stdout.channel.recv_exit_status()
    if rc != 0:
        err = stderr.read().decode(errors='ignore').strip()
        raise RuntimeError(f"更新 {key} 失败: {err}")


COLLAB_TIERS = {
    'readonly-deploy': '只读 + 部署：仅限项目目录读写，无通用 sudo，可选授权重启指定服务',
    'full-shell': '完整 shell，无 sudo：普通用户权限，不加入 sudo/wheel/docker 组',
    'sudo-whitelist': '特定命令 sudo 白名单：仅能免密执行显式列出的绝对路径命令',
    'sftp-only': '只 SFTP，不给 shell：chroot 到指定目录，仅能上传/下载文件',
}


def validate_linux_username(name):
    return re.match(r'^[a-z_][a-z0-9_-]{0,31}$', name) is not None


def generate_password(length=20):
    """生成不含 shell 特殊字符的随机强密码，可安全拼入远程命令字符串。"""
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def _reject_unsafe(value, label):
    """协作者账号相关的字符串会被直接拼进远程 shell 命令，禁止引号/反斜杠/$/反引号等破坏拼接的字符。"""
    if any(ch in value for ch in ('"', "'", '\\', '$', '`')):
        print(f"✗ {label} 包含不允许的字符（\" ' \\ $ ` 均不可用）: {value}")
        sys.exit(1)


def _remote_exec(alias, command, admin_username, timeout=30):
    """在受控别名上执行远程命令；管理员非 root 时自动通过 sudo 整体提权执行。"""
    if admin_username == 'root':
        return run_ssh_command(alias, command, timeout=timeout)
    wrapped = 'sudo bash -c "' + command.replace('"', '\\"') + '"'
    return run_ssh_command(alias, wrapped, timeout=timeout)


def _write_sudoers(alias, admin_username, cuser, lines):
    """写入 /etc/sudoers.d/<user> 白名单，写入后用 visudo 校验语法，失败则回滚删除。"""
    path = f"/etc/sudoers.d/{cuser}"
    check = _remote_exec(alias, f"test -e {path}", admin_username)
    if check.returncode == 0:
        print(f"   ✗ {path} 已存在，为避免覆盖已有规则，操作中止")
        sys.exit(1)
    for line in lines:
        r = _remote_exec(alias, f"echo '{line}' >> {path}", admin_username)
        if r.returncode != 0:
            _remote_exec(alias, f"rm -f {path}", admin_username)
            print(f"   ✗ 写入 sudoers 失败: {r.stderr.strip()}")
            sys.exit(1)
    r = _remote_exec(alias, f"chmod 440 {path}", admin_username)
    if r.returncode != 0:
        _remote_exec(alias, f"rm -f {path}", admin_username)
        print("   ✗ 设置 sudoers 权限失败")
        sys.exit(1)
    check_syntax = _remote_exec(alias, f"visudo -cf {path}", admin_username)
    if check_syntax.returncode != 0:
        _remote_exec(alias, f"rm -f {path}", admin_username)
        print(f"   ✗ sudoers 语法校验失败，已回滚: {check_syntax.stderr.strip()}")
        sys.exit(1)


def cmd_server_add_collaborator(args):
    """创建一个非 root 的受限协作者账号：仅密码登录、按档位授权，不影响 root/已有账号的免密策略。"""
    alias = args.alias
    cuser = args.username
    tier = args.tier

    servers = load_servers()
    if alias not in servers:
        print(f"✗ 服务器 '{alias}' 未找到，请先用 server add 配置好管理员免密访问")
        sys.exit(1)

    if not validate_linux_username(cuser):
        print(f"✗ 用户名 '{cuser}' 不合法（需匹配 ^[a-z_][a-z0-9_-]{{0,31}}$）")
        sys.exit(1)
    if cuser in ('root', 'admin', 'ubuntu', 'ec2-user', 'centos', 'debian'):
        print(f"✗ 拒绝使用 '{cuser}' 作为协作者用户名（保留/易混淆账号名）")
        sys.exit(1)

    host = servers[alias].get('host') or servers[alias].get('ip')
    port = int(servers[alias].get('port', 22))
    admin_username = servers[alias].get('username')

    password = args.password
    if password:
        _reject_unsafe(password, "自定义密码")
    else:
        password = generate_password()

    if args.group:
        _reject_unsafe(args.group, "--group")
    if args.chroot_dir:
        _reject_unsafe(args.chroot_dir, "--chroot-dir")
    for svc in args.restart_service:
        _reject_unsafe(svc, "--restart-service")
        if not re.match(r'^[a-zA-Z0-9_.@-]+$', svc):
            print(f"✗ 服务名不合法: {svc}")
            sys.exit(1)
    for c in args.sudo_cmd:
        _reject_unsafe(c, "--sudo-cmd")
        if not c.startswith('/'):
            print(f"✗ --sudo-cmd 必须是绝对路径: {c}")
            sys.exit(1)

    print(f"\n{'='*60}")
    print("SSH Remote Control - 创建受限协作者账号")
    print(f"{'='*60}")
    print(f"服务器: {host}:{port}  (管理员别名: {alias})")
    print(f"新账号: {cuser}")
    print(f"权限档位: {tier} — {COLLAB_TIERS[tier]}")
    print(f"{'='*60}\n")

    # 步骤1: 确认账号不存在，避免覆盖已有用户
    print("1️⃣ 检查账号是否已存在...")
    result = _remote_exec(alias, f"id {cuser}", admin_username)
    if result.returncode == 0:
        print(f"   ✗ 用户 '{cuser}' 已存在，为避免覆盖已有账号，操作中止")
        print(f"     如需重建，请先手动确认后执行: ssh {alias} \"userdel -r {cuser}\"")
        sys.exit(1)
    print("   ✓ 用户名可用")

    # 步骤2: 档位相关参数预校验
    chroot_dir = None
    if tier == 'sftp-only':
        shell = '/usr/sbin/nologin'
        if not args.chroot_dir or not args.chroot_dir.startswith('/'):
            print("✗ sftp-only 档位需要 --chroot-dir <绝对路径>")
            sys.exit(1)
        chroot_dir = args.chroot_dir.rstrip('/')
    else:
        shell = '/bin/bash'

    if tier == 'readonly-deploy' and args.group:
        check = _remote_exec(alias, f"getent group {args.group}", admin_username)
        if check.returncode != 0:
            print(f"✗ 属组 '{args.group}' 不存在，请先在服务器上创建，或改用已有的项目属组")
            sys.exit(1)

    if tier == 'sudo-whitelist' and not args.sudo_cmd:
        print("✗ sudo-whitelist 档位至少需要一条 --sudo-cmd <绝对路径命令>")
        sys.exit(1)

    # 步骤3: 创建账号并设置密码
    print("\n2️⃣ 创建账号并设置密码...")
    result = _remote_exec(
        alias, f"useradd -m -s {shell} {cuser} && echo '{cuser}:{password}' | chpasswd",
        admin_username
    )
    if result.returncode != 0:
        print(f"   ✗ 创建失败: {result.stderr.strip()}")
        sys.exit(1)
    print("   ✓ 账号已创建")

    # 步骤4: 按档位授权
    print(f"\n3️⃣ 按档位 '{tier}' 授权...")
    if tier == 'readonly-deploy':
        if args.group:
            r = _remote_exec(alias, f"usermod -aG {args.group} {cuser}", admin_username)
            if r.returncode != 0:
                print(f"   ✗ 加入属组失败: {r.stderr.strip()}")
                sys.exit(1)
            print(f"   ✓ 已加入属组 '{args.group}'（依赖该目录已设 setgid + 组可写，如 chmod 2775）")
        sudo_lines = [
            f"{cuser} ALL=(root) NOPASSWD: /bin/systemctl restart {svc}, /bin/systemctl status {svc}"
            for svc in args.restart_service
        ]
        if sudo_lines:
            _write_sudoers(alias, admin_username, cuser, sudo_lines)
            print(f"   ✓ 已授权免密重启服务: {', '.join(args.restart_service)}")
        if not args.group and not sudo_lines:
            print("   ⚠ 未指定 --group 或 --restart-service，该账号目前仅有基础登录权限，无额外授权")

    elif tier == 'full-shell':
        print("   ✓ 无额外授权（未加入 sudo/wheel/docker 组，仅普通用户权限）")

    elif tier == 'sudo-whitelist':
        sudo_lines = [f"{cuser} ALL=(root) NOPASSWD: {c}" for c in args.sudo_cmd]
        _write_sudoers(alias, admin_username, cuser, sudo_lines)
        print(f"   ✓ 已写入 sudo 白名单（{len(args.sudo_cmd)} 条命令，未列出的命令一律拒绝）")

    elif tier == 'sftp-only':
        cmds = (
            f"mkdir -p {chroot_dir} && chown root:root {chroot_dir} && chmod 755 {chroot_dir} && "
            f"mkdir -p {chroot_dir}/upload && chown {cuser}:{cuser} {chroot_dir}/upload && chmod 750 {chroot_dir}/upload"
        )
        r = _remote_exec(alias, cmds, admin_username)
        if r.returncode != 0:
            print(f"   ✗ chroot 目录准备失败: {r.stderr.strip()}")
            sys.exit(1)
        print(f"   ✓ chroot 目录已就绪: {chroot_dir}（可写子目录: {chroot_dir}/upload）")

    # 步骤5: 配置 sshd —— 仅该账号密码登录，且关闭该账号的免密，不影响其他账号
    print("\n4️⃣ 配置 sshd（仅该账号密码登录，不影响其他账号/root）...")
    check_block = _remote_exec(alias, f"grep -q '^Match User {cuser}$' /etc/ssh/sshd_config", admin_username)
    if check_block.returncode == 0:
        print(f"   ✗ sshd_config 中已存在 'Match User {cuser}' 块，为避免重复/冲突配置，操作中止")
        print("     请手动检查 /etc/ssh/sshd_config 后重试")
        sys.exit(1)

    backup = _remote_exec(
        alias, "cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%F-%H%M%S)", admin_username
    )
    if backup.returncode != 0:
        print(f"   ✗ 备份 sshd_config 失败: {backup.stderr.strip()}")
        sys.exit(1)

    match_lines = [
        f"Match User {cuser}",
        "    PasswordAuthentication yes",
        "    PubkeyAuthentication no",
        "    AuthenticationMethods password",
    ]
    if tier == 'sftp-only':
        match_lines += [
            f"    ChrootDirectory {chroot_dir}",
            "    ForceCommand internal-sftp",
            "    AllowTcpForwarding no",
            "    X11Forwarding no",
        ]
    append_cmd = "printf '\\n" + "\\n".join(match_lines) + "\\n' >> /etc/ssh/sshd_config"
    r = _remote_exec(alias, append_cmd, admin_username)
    if r.returncode != 0:
        print(f"   ✗ 写入 Match 块失败: {r.stderr.strip()}")
        sys.exit(1)

    check = _remote_exec(alias, "sshd -t", admin_username)
    if check.returncode != 0:
        print(f"   ✗ sshd -t 语法检查失败，配置未生效，请检查备份并手动排查: {check.stderr.strip()}")
        sys.exit(1)

    reload_r = _remote_exec(alias, "systemctl reload sshd", admin_username)
    if reload_r.returncode != 0:
        print(f"   ✗ 重载 sshd 失败: {reload_r.stderr.strip()}")
        sys.exit(1)
    print("   ✓ sshd 已重载，仅该账号可密码登录，root/其他账号策略未变")

    # 步骤6: 只读校验（不测试密码登录本身，遵守技能"禁止 sshpass"规则）
    print("\n5️⃣ 校验生效策略...")
    verify = _remote_exec(
        alias,
        f"sshd -T -C user={cuser},host=localhost,addr=127.0.0.1 2>/dev/null | "
        f"grep -E 'passwordauthentication|pubkeyauthentication|forcecommand|chrootdirectory'",
        admin_username
    )
    if verify.returncode == 0 and verify.stdout.strip():
        for line in verify.stdout.strip().splitlines():
            print(f"   {line}")
    else:
        print("   ⚠ 当前系统不支持 sshd -T -C 按用户读取生效策略，可手动执行:")
        print(f"     ssh {alias} \"sshd -T -C user={cuser} 2>&1 | grep -i password\"")

    print(f"\n{'='*60}")
    print("✅ 协作者账号创建完成")
    print(f"{'='*60}")
    print(f"\n账号: {cuser}")
    print(f"密码: {password}")
    print("⚠️  密码仅在此显示一次，请立即通过安全渠道转发给协作者并妥善保存，不要留在本机明文历史中")
    print("\n协作者连接方式（对方在自己机器上执行，不需要你的私钥/别名）:")
    print(f"  ssh {cuser}@{host} -p {port}")
    print("\n注意: 该账号已关闭免密登录（PubkeyAuthentication no），只能用上面的密码登录")


def diagnose_connection_failure(alias, ip, username, password):
    """连接失败时给出更明确的诊断结论。"""
    print("\n   诊断信息:")
    try:
        probe = run_local_command(
            ['ssh', '-vvv', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', alias, 'echo ok'],
            timeout=20
        )
        probe_msg = (probe.stderr or "") + (probe.stdout or "")
    except Exception as e:
        probe_msg = str(e)

    if "REMOTE HOST IDENTIFICATION HAS CHANGED" in probe_msg:
        print("   - 检测到主机指纹冲突")
        print(f"   - 处理命令: ssh-keygen -R {ip}")
        return

    if "Permission denied (password)" in probe_msg:
        print("   - 服务器拒绝公钥认证，当前回退到密码认证")
        try:
            import paramiko
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=username, password=password, timeout=10)
            stdin, stdout, stderr = ssh.exec_command(
                "sshd -T | grep -E 'pubkeyauthentication|passwordauthentication|authorizedkeysfile'"
            )
            info = stdout.read().decode(errors='ignore').strip()
            ssh.close()
            if info:
                print("   - 服务端 sshd 当前策略:")
                for line in info.splitlines():
                    print(f"     {line}")
            else:
                print("   - 未读取到 sshd 策略，请手动执行: sshd -T")
        except Exception as e:
            print(f"   - 无法读取服务端 sshd 策略: {e}")
        print(f"   - 建议执行: python sshctrl.py server repair-pubkey {alias} <密码>")
        return

    print("   - 未匹配到已知特征，请执行:")
    print(f"     ssh -vvv -o BatchMode=yes {alias} \"echo ok\"")


def validate_host(host):
    """验证主机名或IP地址格式。"""
    ip_pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if re.match(ip_pattern, host):
        parts = host.split('.')
        return all(0 <= int(part) <= 255 for part in parts)

    # 域名（宽松校验）
    domain_pattern = r'^[a-zA-Z0-9][a-zA-Z0-9.-]{0,252}[a-zA-Z0-9]$'
    return re.match(domain_pattern, host) is not None


# ============== Server 子命令 ==============

def cmd_server_add(args):
    """配置服务器SSH免密连接（核心SOP流程）。"""
    import paramiko

    host = args.host
    port = args.port
    username = args.username
    password = args.password
    alias = args.alias or host.replace('.', '_').replace('-', '_')

    if not validate_host(host):
        print(f"✗ 无效的主机地址: {host}")
        sys.exit(1)
    if not (1 <= port <= 65535):
        print(f"✗ 无效端口: {port}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print("SSH Remote Control - 配置服务器免密连接")
    print(f"{'='*60}")
    print(f"服务器: {host}:{port}")
    print(f"用户: {username}")
    print(f"别名: {alias}")
    print(f"{'='*60}\n")

    # 步骤1: 测试密码连接
    print("1️⃣ 测试SSH连接...")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password, timeout=10)
        print("   ✓ 连接成功")

        stdin, stdout, stderr = ssh.exec_command('uname -a')
        info = stdout.read().decode().strip()
        hostname = info.split()[1] if info else '未知'
        print(f"   主机名: {hostname}")
        ssh.close()
    except paramiko.AuthenticationException:
        print("   ✗ 认证失败，请检查用户名和密码")
        sys.exit(1)
    except Exception as e:
        print(f"   ✗ 连接失败: {e}")
        sys.exit(1)

    # 步骤2: 生成SSH密钥
    print("\n2️⃣ 生成SSH密钥...")
    home = os.path.expanduser('~')
    key_name = f"id_ed25519_{host.replace('.', '_').replace('-', '_')}_{port}"
    key_path = os.path.join(home, '.ssh', key_name)

    if os.path.exists(key_path):
        print(f"   ✓ 密钥已存在: {key_name}")
    else:
        result = subprocess.run(
            ['ssh-keygen', '-t', 'ed25519', '-f', key_path, '-N', '', '-C', f'sshctrl-{host}:{port}'],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            print(f"   ✓ 密钥已生成: {key_name}")
        else:
            print(f"   ✗ 密钥生成失败: {result.stderr}")
            sys.exit(1)

    with open(key_path + '.pub') as f:
        pubkey = f.read().strip()

    # 步骤3: 上传公钥
    print("\n3️⃣ 上传公钥到服务器...")
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password, timeout=10)

        stdin, stdout, stderr = ssh.exec_command(f'eval echo ~{username}')
        user_home = stdout.read().decode().strip() or ('/root' if username == 'root' else f'/home/{username}')
        print(f"   家目录: {user_home}")

        ssh.exec_command(f'mkdir -p {user_home}/.ssh && chmod 700 {user_home}/.ssh')

        sftp = ssh.open_sftp()
        auth_keys_path = f'{user_home}/.ssh/authorized_keys'

        try:
            with sftp.open(auth_keys_path, 'a') as f:
                f.write(pubkey + '\n')
            sftp.chmod(auth_keys_path, 0o600)
            print("   ✓ 公钥已上传")
        finally:
            sftp.close()
        ssh.close()
    except Exception as e:
        print(f"   ✗ 上传失败: {e}")
        sys.exit(1)

    # 步骤4: 配置本地SSH
    print("\n4️⃣ 配置本地SSH...")
    ssh_dir = os.path.join(home, '.ssh')
    os.makedirs(ssh_dir, exist_ok=True)

    if platform.system() == 'Windows':
        try:
            subprocess.run([
                'powershell.exe', '-NoProfile', '-Command',
                f"$path = '{key_path}'; $acl = Get-Acl $path; "
                f"$acl.SetAccessRuleProtection($true, $false); "
                f"$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("
                f"[System.Security.Principal.WindowsIdentity]::GetCurrent().Name,"
                f"'FullControl','Allow'); $acl.SetAccessRule($rule); Set-Acl $path $acl"
            ], check=True, capture_output=True, timeout=30)
            print("   ✓ Windows权限已修复")
        except:
            print("   ⚠ 权限修复失败，请手动处理")
    else:
        os.chmod(key_path, 0o600)
        print("   ✓ 权限已设置为600")

    ssh_config = os.path.join(ssh_dir, 'config')
    existing_aliases = []
    if os.path.exists(ssh_config):
        with open(ssh_config) as f:
            for line in f:
                if line.strip().startswith('Host '):
                    existing_aliases.append(line.split()[1])

    if alias in existing_aliases:
        print(f"   ⚠ 别名 '{alias}' 已存在")
    else:
        config_entry = f"""
Host {alias}
    HostName {host}
    Port {port}
    User {username}
    IdentityFile ~/.ssh/{key_name}
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    ServerAliveInterval 60
    ServerAliveCountMax 3
    TCPKeepAlive yes
"""
        with open(ssh_config, 'a') as f:
            f.write(config_entry)
        print(f"   ✓ SSH别名 '{alias}' 已添加")

    # 保存服务器信息
    servers = load_servers()
    servers[alias] = {'host': host, 'ip': host, 'port': port, 'username': username}
    save_servers(servers)

    # 步骤5: 验证免密连接
    print("\n5️⃣ 验证免密连接...")
    time.sleep(1)
    try:
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=10', alias, 'echo "✓ 免密连接成功"'],
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0 and '免密连接成功' in result.stdout:
            print("   ✓ 免密连接验证通过")
        else:
            print("   ⚠ 免密连接验证失败，请检查:")
            print(f"      ssh {alias} \"whoami\"")
            diagnose_connection_failure(alias, host, username, password)
    except subprocess.TimeoutExpired:
        # 公钥可能已正确上传，只是网络抖动导致验证本身超时；
        # 不应让整个 server add 以未捕获异常崩溃（2026-08-12 复盘教训）。
        print("   ⚠ 验证超时（15s），公钥可能已上传成功，请手动确认:")
        print(f"      ssh -o BatchMode=yes {alias} \"whoami\"")

    print(f"\n{'='*60}")
    print("✅ 服务器配置完成！")
    print(f"{'='*60}")
    print(f"\n验证命令: ssh {alias} \"whoami && hostname\"")
    print(f"\n日常操作示例:")
    print(f"  ssh {alias} \"docker ps\"")
    print(f"  scp file.txt {alias}:/remote/path/")
    print(f"\n⚠️  不要再使用密码认证，所有操作通过SSH别名完成")


def cmd_server_list(args):
    """列出已配置的服务器。"""
    servers = load_servers()

    if not servers:
        print("没有已配置的服务器。")
        print(f"\n添加服务器: sshctrl server add <IP> <用户名> <密码> [别名]")
        return

    print(f"\n已配置的服务器 ({len(servers)}台):\n")
    for alias, info in sorted(servers.items()):
        print(f"  {alias}")
        display_host = info.get('host') or info.get('ip', 'N/A')
        print(f"    主机: {display_host}")
        print(f"    端口: {info.get('port', 22)}")
        print(f"    用户: {info.get('username', 'N/A')}")
        print()


def cmd_server_remove(args):
    """移除服务器配置。"""
    alias = args.alias
    home = os.path.expanduser('~')

    servers = load_servers()
    if alias not in servers:
        print(f"✗ 服务器 '{alias}' 不存在")
        sys.exit(1)

    del servers[alias]
    save_servers(servers)
    print(f"✓ 已从配置列表移除: {alias}")

    ssh_config = os.path.join(home, '.ssh', 'config')
    if os.path.exists(ssh_config):
        with open(ssh_config) as f:
            lines = f.readlines()

        new_lines = []
        skip_block = False
        for line in lines:
            if line.strip().startswith('Host ' + alias):
                skip_block = True
                continue
            elif skip_block and line.strip().startswith('Host '):
                skip_block = False
            if not skip_block:
                new_lines.append(line)

        with open(ssh_config, 'w') as f:
            f.writelines(new_lines)
        print(f"✓ 已从SSH配置移除: {alias}")

    subprocess.run(['ssh-keygen', '-R', alias], capture_output=True)
    print(f"✓ 已删除主机密钥")


def cmd_server_ssh(args):
    """SSH连接到服务器。"""
    alias = args.alias
    command = args.command

    servers = load_servers()
    if alias not in servers:
        print(f"✗ 服务器 '{alias}' 未找到")
        print(f"可用服务器: {', '.join(servers.keys()) if servers else '无'}")
        sys.exit(1)

    if command:
        result = run_ssh_command(alias, command)
        print(result.stdout)
        sys.exit(result.returncode)
    else:
        os.execvp('ssh', ['ssh', alias])


def cmd_server_repair_pubkey(args):
    """自动修复服务端公钥认证配置，并验证免密连接。"""
    import paramiko

    alias = args.alias
    password = args.password

    servers = load_servers()
    if alias not in servers:
        print(f"✗ 服务器 '{alias}' 未找到")
        print(f"可用服务器: {', '.join(servers.keys()) if servers else '无'}")
        sys.exit(1)

    host = servers[alias].get('host') or servers[alias].get('ip')
    port = int(servers[alias].get('port', 22))
    username = servers[alias].get('username')

    print(f"\n{'='*60}")
    print("SSH Remote Control - 自动修复服务端公钥认证")
    print(f"{'='*60}")
    print(f"服务器: {host}:{port}")
    print(f"用户: {username}")
    print(f"别名: {alias}")
    print(f"{'='*60}\n")

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password, timeout=10)
        print("1️⃣ 密码连接测试...")
        print("   ✓ 连接成功")

        print("\n2️⃣ 备份并更新 /etc/ssh/sshd_config ...")
        stdin, stdout, stderr = ssh.exec_command(
            "cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%F-%H%M%S)"
        )
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            err = stderr.read().decode(errors='ignore').strip()
            raise RuntimeError(f"备份 sshd_config 失败: {err}")

        _upsert_remote_sshd_config(ssh, "PubkeyAuthentication", "yes")
        _upsert_remote_sshd_config(
            ssh, "AuthorizedKeysFile", ".ssh/authorized_keys .ssh/authorized_keys2"
        )
        if username == "root":
            # PermitRootLogin 必须至少是 prohibit-password 才能让 root 走通公钥认证，
            # 但这会附带关闭 root 的密码登录（即使 PasswordAuthentication 仍是 yes）。
            # 必须显式告知，避免变成"配置被静默改动"式的排查（2026-08-12 复盘教训）。
            _upsert_remote_sshd_config(ssh, "PermitRootLogin", "prohibit-password")
            print("   ⚠ 已将 PermitRootLogin 设为 prohibit-password：")
            print("     root 之后只能用密钥登录，密码登录 root 将不再可用。")
        print("   ✓ 配置已更新")

        print("\n3️⃣ 语法检查并重载 sshd ...")
        stdin, stdout, stderr = ssh.exec_command("sshd -t")
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            err = stderr.read().decode(errors='ignore').strip()
            raise RuntimeError(f"sshd -t 失败: {err}")

        stdin, stdout, stderr = ssh.exec_command("systemctl reload sshd")
        rc = stdout.channel.recv_exit_status()
        if rc != 0:
            err = stderr.read().decode(errors='ignore').strip()
            raise RuntimeError(f"重载 sshd 失败: {err}")
        print("   ✓ sshd 重载成功")

        stdin, stdout, stderr = ssh.exec_command(
            "sshd -T | grep -E 'pubkeyauthentication|passwordauthentication|authorizedkeysfile|permitrootlogin'"
        )
        policy = stdout.read().decode(errors='ignore').strip()
        print("\n4️⃣ 服务端生效策略:")
        if policy:
            for line in policy.splitlines():
                print(f"   {line}")
        else:
            print("   ⚠ 未读取到策略输出")

        ssh.close()

        print("\n5️⃣ 本地免密回归验证...")
        verify = run_local_command(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', alias, 'whoami && hostname'],
            timeout=20
        )
        if verify.returncode == 0:
            print("   ✓ 免密验证通过")
            out = (verify.stdout or "").strip()
            if out:
                print("   返回:")
                for line in out.splitlines():
                    print(f"   {line}")
        else:
            print("   ⚠ 免密验证未通过")
            err = (verify.stderr or "").strip()
            if err:
                print(f"   错误: {err}")
            print(f"   建议排查: ssh -vvv -o BatchMode=yes {alias} \"echo ok\"")

        print(f"\n{'='*60}")
        print("✅ 修复流程执行完成")
        print(f"{'='*60}")

    except paramiko.AuthenticationException:
        print("✗ 密码认证失败，请检查密码")
        sys.exit(1)
    except Exception as e:
        print(f"✗ 修复失败: {e}")
        sys.exit(1)


# ============== 主入口 ==============

def main():
    parser = argparse.ArgumentParser(
        description="SSH Remote Control - SSH免密连接配置工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
核心SOP流程：
  1. sshctrl server add <host> <用户> <密码> [别名] [--port 端口]  # 配置免密
  2. ssh <别名> "命令"                              # 日常操作

示例:
  sshctrl server add 192.168.1.100 root password myserver
  sshctrl server add connect.nmb2.seetacloud.com root password myserver --port 20605
  sshctrl server repair-pubkey myserver password
  sshctrl server list
  sshctrl server ssh myserver "uptime"
        """
    )
    parser.add_argument('--version', action='version', version=f'sshctrl {VERSION}')

    subparsers = parser.add_subparsers(dest='command', help='可用子命令')

    # server 子命令
    server_parser = subparsers.add_parser('server', help='服务器管理')
    server_subparsers = server_parser.add_subparsers(dest='server_command')

    add_parser = server_subparsers.add_parser('add', help='添加并配置新服务器')
    add_parser.add_argument('host', help='服务器主机（IP或域名）')
    add_parser.add_argument('username', help='用户名')
    add_parser.add_argument('password', help='密码')
    add_parser.add_argument('alias', nargs='?', help='SSH别名（可选）')
    add_parser.add_argument('--port', type=int, default=22, help='SSH端口（默认22）')

    server_subparsers.add_parser('list', help='列出所有已配置的服务器')

    remove_parser = server_subparsers.add_parser('remove', help='移除服务器配置')
    remove_parser.add_argument('alias', help='要移除的服务器别名')

    ssh_parser = server_subparsers.add_parser('ssh', help='SSH连接到服务器')
    ssh_parser.add_argument('alias', help='服务器别名')
    ssh_parser.add_argument('command', nargs='?', default=None, help='要执行的命令（可选）')

    repair_parser = server_subparsers.add_parser(
        'repair-pubkey',
        help='自动修复服务端公钥认证并验证免密连接'
    )
    repair_parser.add_argument('alias', help='服务器别名')
    repair_parser.add_argument('password', help='服务器密码（仅用于本次修复）')

    addcollab_parser = server_subparsers.add_parser(
        'add-collaborator',
        help='为协作者创建受限账号（仅密码登录、非 root、按档位授权，不影响其他账号免密策略）'
    )
    addcollab_parser.add_argument('alias', help='已配置好免密访问的管理员别名')
    addcollab_parser.add_argument('username', help='要创建的协作者 Linux 用户名')
    addcollab_parser.add_argument(
        'tier', choices=list(COLLAB_TIERS.keys()),
        help='权限档位: ' + '; '.join(f"{k}={v}" for k, v in COLLAB_TIERS.items())
    )
    addcollab_parser.add_argument('--password', help='指定密码（不指定则自动生成随机强密码，只显示一次）')
    addcollab_parser.add_argument('--group', help='[readonly-deploy] 已存在的项目属组，授予该组对项目目录的写权限')
    addcollab_parser.add_argument(
        '--restart-service', action='append', default=[],
        help='[readonly-deploy] 允许免密重启/查看状态的 systemd 服务名，可重复指定'
    )
    addcollab_parser.add_argument(
        '--sudo-cmd', action='append', default=[],
        help='[sudo-whitelist] 允许免密执行的绝对路径命令，可重复指定'
    )
    addcollab_parser.add_argument('--chroot-dir', help='[sftp-only] SFTP chroot 根目录（绝对路径）')

    args = parser.parse_args()

    if args.command == 'server':
        if args.server_command == 'add':
            cmd_server_add(args)
        elif args.server_command == 'list':
            cmd_server_list(args)
        elif args.server_command == 'remove':
            cmd_server_remove(args)
        elif args.server_command == 'ssh':
            cmd_server_ssh(args)
        elif args.server_command == 'repair-pubkey':
            cmd_server_repair_pubkey(args)
        elif args.server_command == 'add-collaborator':
            cmd_server_add_collaborator(args)
        else:
            server_parser.print_help()
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
