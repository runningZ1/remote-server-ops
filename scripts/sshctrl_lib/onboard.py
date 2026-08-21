#!/usr/bin/env python3
import os
import platform
import subprocess
import sys
import time

import paramiko

from .common import (
    load_servers,
    paramiko_client,
    resolve_secret_password,
    run_ssh_command,
    save_servers,
    validate_host,
)
from .repair import build_vnc_auth_rescue_script, diagnose_connection_failure


def cmd_server_add(args):
    """配置服务器SSH免密连接（核心SOP流程）。"""
    import paramiko

    host = args.host
    port = args.port
    username = args.username
    password = resolve_secret_password(args.password)
    alias = args.alias.strip()

    if not alias:
        print("✗ 别名不能为空。别名必须由用户显式指定（项目名/云厂商名优先，实在没有再用IP），")
        print("  不要自动用IP拼一个——这一步不能替用户做主，先问清楚再重跑。")
        sys.exit(1)

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
        ssh = paramiko_client()
        ssh.connect(host, port=port, username=username, password=password, timeout=10)
        print("   ✓ 连接成功")

        stdin, stdout, stderr = ssh.exec_command('uname -a')
        info = stdout.read().decode().strip()
        hostname = info.split()[1] if info else '未知'
        print(f"   主机名: {hostname}")
        ssh.close()
    except paramiko.AuthenticationException:
        print("   ✗ 认证失败（用户名/密码可能正确，但服务器策略拒绝了登录）")
        print("\n   常见原因：sshd_config 里 PasswordAuthentication=no、")
        print("   AllowUsers 白名单未包含该用户、PermitRootLogin=no 等。")
        print("   仅凭 SSH 报错无法区分具体是哪一项——因为登录都还没成功，")
        print("   本工具连不进去查看服务器配置，需要你通过服务商的 VNC/")
        print("   控制台（不经过SSH）登录服务器后运行下面脚本一次性排查：\n")
        print(build_vnc_auth_rescue_script(username))
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
        ssh = paramiko_client()
        ssh.connect(host, port=port, username=username, password=password, timeout=10)

        stdin, stdout, stderr = ssh.exec_command(f'eval echo ~{username}')
        user_home = stdout.read().decode().strip() or ('/root' if username == 'root' else f'/home/{username}')
        print(f"   家目录: {user_home}")

        ssh.exec_command(f'mkdir -p {user_home}/.ssh && chmod 700 {user_home}/.ssh')

        sftp = ssh.open_sftp()
        auth_keys_path = f'{user_home}/.ssh/authorized_keys'

        try:
            existing = ""
            try:
                with sftp.open(auth_keys_path, 'r') as f:
                    existing = f.read().decode('utf-8', errors='ignore')
            except IOError:
                existing = ""
            if pubkey in existing:
                print("   ✓ 公钥已存在，跳过重复写入")
            else:
                with sftp.open(auth_keys_path, 'a') as f:
                    f.write(pubkey + '\n')
                print("   ✓ 公钥已上传")
            sftp.chmod(auth_keys_path, 0o600)
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
        print(f"\n添加服务器: sshctrl server add <IP> <用户名> <密码> <别名>")
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
            stripped = line.strip()
            if stripped.lower().startswith('host '):
                hosts = stripped.split()[1:]
                if hosts == [alias]:
                    skip_block = True
                    continue
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
