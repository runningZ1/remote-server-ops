#!/usr/bin/env python3
import re
import secrets
import string
import sys

from sshctrl_common import load_servers, resolve_secret_password, run_ssh_command, RELOAD_SSHD


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
        password = resolve_secret_password(password, "自定义密码") if password == "-" else password
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

    reload_r = _remote_exec(
        alias,
        "systemctl reload sshd || systemctl reload ssh || systemctl restart sshd || systemctl restart ssh",
        admin_username,
    )
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

