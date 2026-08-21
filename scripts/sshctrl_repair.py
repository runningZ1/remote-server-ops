#!/usr/bin/env python3
import os
import sys

import paramiko

from sshctrl_common import (
    RELOAD_SSHD,
    _print_command_output,
    _upsert_remote_sshd_config,
    load_servers,
    paramiko_client,
    resolve_secret_password,
    run_local_command,
    run_sftp_probe,
)


# 2026-07-11 复盘：一次真实上线遇到密码认证被拒绝，根因分散在四处
# sshd_config 设置里（PasswordAuthentication no 写在第1行、AllowUsers 白名单
# 漏了目标用户、PermitRootLogin no、Subsystem sftp 整段缺失），每处都要单独
# 靠用户在 VNC/控制台里截图确认才发现，来回了 5 轮。以后密码认证在 step 1
# 就失败时，直接把这四处一次性检查+修复的脚本打印给用户，避免逐项排查。
VNC_AUTH_RESCUE_SCRIPT_TEMPLATE = """\
# ============================================================
# 在服务器的 VNC/控制台里（不经过SSH）粘贴执行以下脚本
# 一次性检查并修复导致密码登录被拒绝的四个常见原因：
#   1) PasswordAuthentication no（且可能在文件靠前的行生效覆盖后面的 yes）
#   2) AllowUsers/AllowGroups 白名单里没有目标用户
#   3) PermitRootLogin no（若目标用户是 root）
#   4) Subsystem sftp 未配置，导致后续上传公钥/SFTP失败
# ============================================================
set -e
CFG=/etc/ssh/sshd_config
TARGET_USER="{username}"

cp "$CFG" "$CFG.bak.$(date +%s)"
echo "已备份: $CFG.bak.*"

# 1) PasswordAuthentication：确保生效值是 yes（sshd按首次出现的行生效）
if grep -qE '^[[:space:]]*PasswordAuthentication' "$CFG"; then
    sed -i '0,/^[[:space:]]*PasswordAuthentication/{{s/^[[:space:]]*PasswordAuthentication.*/PasswordAuthentication yes/}}' "$CFG"
else
    echo "PasswordAuthentication yes" >> "$CFG"
fi

# 2) AllowUsers/AllowGroups：如果存在白名单但没有目标用户，追加进去
if grep -qE '^[[:space:]]*AllowUsers' "$CFG" && ! grep -E '^[[:space:]]*AllowUsers' "$CFG" | grep -qw "$TARGET_USER"; then
    sed -i "/^[[:space:]]*AllowUsers/ s/\\$/ $TARGET_USER/" "$CFG"
fi

# 3) PermitRootLogin：目标用户是root时必须允许
if [ "$TARGET_USER" = "root" ]; then
    if grep -qE '^[[:space:]]*PermitRootLogin' "$CFG"; then
        sed -i 's/^[[:space:]]*PermitRootLogin.*/PermitRootLogin yes/' "$CFG"
    else
        echo "PermitRootLogin yes" >> "$CFG"
    fi
fi

# 4) SFTP subsystem：完全缺失时补上（后续上传公钥依赖SFTP）
if ! grep -qE '^[[:space:]]*Subsystem[[:space:]]+sftp' "$CFG"; then
    SFTP_BIN=$(command -v /usr/lib/openssh/sftp-server || command -v /usr/libexec/openssh/sftp-server || echo internal-sftp)
    echo "Subsystem sftp $SFTP_BIN" >> "$CFG"
fi

echo "== 修改后关键配置 =="
grep -nE '^[[:space:]]*(PasswordAuthentication|PermitRootLogin|AllowUsers|Subsystem[[:space:]]+sftp)' "$CFG"

sshd -t && (systemctl restart sshd || systemctl restart ssh)
echo "== sshd -T 生效值确认 =="
sshd -T | grep -Ei 'passwordauthentication|permitrootlogin'
echo "完成。改完后不要关闭本 VNC 窗口，先在别的终端测试:"
echo "  ssh {username}@<host> \\"whoami\\""
"""


def build_vnc_auth_rescue_script(username: str) -> str:
    """构造一次性覆盖四类常见sshd拦截原因的 VNC 控制台修复脚本。"""
    return VNC_AUTH_RESCUE_SCRIPT_TEMPLATE.format(username=username)


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
            ssh = paramiko_client()
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
        print(f"   - 建议执行: python scripts/sshctrl.py server repair-pubkey {alias} <密码>")
        return

    print("   - 未匹配到已知特征，请执行:")
    print(f"     ssh -vvv -o BatchMode=yes {alias} \"echo ok\"")


def classify_ssh_debug_output(output):
    """把 ssh -vvv 输出归类到网络、认证或子系统层。"""
    lowered = output.lower()
    if "connection timed out" in lowered or "operation timed out" in lowered:
        return "网络/端口层: 连接超时，优先检查 IP、端口、安全组、防火墙和本地网络。"
    if "connection refused" in lowered:
        return "服务监听层: 端口可达但被拒绝，优先检查 sshd 是否启动并监听该端口。"
    if "remote host identification has changed" in lowered:
        return "本机 known_hosts 层: 主机指纹冲突，确认服务器身份后执行 ssh-keygen -R <host>。"
    if "permission denied" in lowered or "authentication failed" in lowered:
        return "认证层: SSH 握手已进入认证阶段，优先检查用户、密码、公钥、PermitRootLogin、PasswordAuthentication 和 authorized_keys。"
    if "subsystem request failed" in lowered or "unable to start subsystem" in lowered:
        return "SFTP subsystem 层: SSH 认证可能已通过，但服务端 sftp 子系统启动失败。"
    if "authentication succeeded" in lowered:
        return "认证层: SSH 认证成功；若文件传输失败，请继续检查 SFTP subsystem。"
    if "connection established" in lowered or "handshake" in lowered:
        return "握手/认证边界: TCP 已建立，继续根据后续 Permission denied 或 subsystem 日志定位。"
    return "未归类: 请保留完整 ssh -vvv 输出，并结合服务端 sshd -T 与日志继续排查。"


def cmd_server_repair_pubkey(args):
    """自动修复服务端公钥认证配置，并验证免密连接。"""
    import paramiko

    alias = args.alias
    password = resolve_secret_password(args.password)

    servers = load_servers()
    if alias not in servers:
        print(f"✗ 服务器 '{alias}' 未找到")
        print(f"可用服务器: {', '.join(servers.keys()) if servers else '无'}")
        sys.exit(1)

    host = servers[alias].get('host') or servers[alias].get('ip')
    port = int(servers[alias].get('port', 22))
    username = servers[alias].get('username')

    print(f"\n{'='*60}")
    print("Remote Server Ops - 自动修复服务端公钥认证")
    print(f"{'='*60}")
    print(f"服务器: {host}:{port}")
    print(f"用户: {username}")
    print(f"别名: {alias}")
    print(f"{'='*60}\n")

    try:
        ssh = paramiko_client()
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
            # PermitRootLogin 必须至少允许 prohibit-password 才能让 root
            # 走通公钥认证；这一步会附带关闭 root 的密码登录，明确告知用户，
            # 避免变成又一次"配置被静默改动"排查（2026-07-11 复盘教训，
            # 2026-08-12 再次独立踩坑确认）。
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

        stdin, stdout, stderr = ssh.exec_command(
            "systemctl reload sshd || systemctl reload ssh || systemctl restart sshd || systemctl restart ssh"
        )
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


def cmd_server_diagnose(args):
    """只读分层诊断：本地 SSH 解析、BatchMode 验证、服务端 sshd 策略、SFTP 子系统。"""
    alias = args.alias

    print(f"\n{'='*60}")
    print("Remote Server Ops - 分层诊断")
    print(f"{'='*60}")
    print(f"别名: {alias}")
    print(f"{'='*60}")

    print("\n1️⃣ 本地 SSH 有效配置")
    ssh_g = run_local_command(['ssh', '-G', alias], timeout=10)
    if ssh_g.returncode == 0:
        wanted = ('hostname ', 'user ', 'port ', 'identityfile ')
        for line in (ssh_g.stdout or '').splitlines():
            if line.lower().startswith(wanted):
                print(f"   {line}")
    else:
        _print_command_output("ssh -G 失败", ssh_g)

    print("\n2️⃣ 本地免密认证探测")
    probe = run_local_command(
        ['ssh', '-vvv', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', alias, 'echo SSH_OK'],
        timeout=20
    )
    combined = (probe.stderr or "") + (probe.stdout or "")
    print(f"   返回码: {probe.returncode}")
    print(f"   归类: {classify_ssh_debug_output(combined)}")
    if probe.returncode == 0:
        print("   ✓ BatchMode 免密 SSH 通过")
    else:
        tail = "\n".join(combined.strip().splitlines()[-12:])
        if tail:
            print("   关键尾部日志:")
            for line in tail.splitlines():
                print(f"   {line}")
        print(f"   建议: python scripts/sshctrl.py server repair-pubkey {alias} <密码>")
        if not args.full:
            return 2

    print("\n3️⃣ 服务端 sshd 生效策略")
    policy_cmd = (
        "sshd -T 2>/dev/null | "
        "grep -Ei 'permitrootlogin|passwordauthentication|pubkeyauthentication|"
        "kbdinteractiveauthentication|usepam|authorizedkeysfile|subsystem' || true"
    )
    policy = run_local_command(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', alias, policy_cmd], timeout=20)
    if policy.returncode == 0 and (policy.stdout or '').strip():
        for line in policy.stdout.strip().splitlines():
            print(f"   {line}")
    else:
        _print_command_output("未能读取 sshd -T", policy)

    print("\n4️⃣ SFTP subsystem 配置扫描")
    sftp_cfg_cmd = (
        "grep -Rni '^[[:space:]]*Subsystem[[:space:]]\\+sftp' "
        "/etc/ssh /etc/ssh/sshd_config.d 2>/dev/null || true"
    )
    sftp_cfg = run_local_command(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', alias, sftp_cfg_cmd], timeout=20)
    if (sftp_cfg.stdout or '').strip():
        for line in sftp_cfg.stdout.strip().splitlines():
            print(f"   {line}")
    else:
        print("   ⚠ 未发现显式 Subsystem sftp 配置；如 SFTP 失败，建议修复为 internal-sftp。")

    print("\n5️⃣ SFTP 启动探测")
    sftp_probe = run_sftp_probe(alias, timeout=20)
    sftp_output = (sftp_probe.stderr or "") + (sftp_probe.stdout or "")
    print(f"   返回码: {sftp_probe.returncode}")
    print(f"   归类: {classify_ssh_debug_output(sftp_output)}")
    if sftp_probe.returncode == 0:
        print("   ✓ SFTP subsystem 可启动")
    else:
        tail = "\n".join(sftp_output.strip().splitlines()[-12:])
        if tail:
            print("   关键尾部日志:")
            for line in tail.splitlines():
                print(f"   {line}")
        print(f"   建议: python scripts/sshctrl.py server repair-sftp {alias}")

    print(f"\n{'='*60}")
    print("诊断完成")
    print(f"{'='*60}")
    return 0


def cmd_server_repair_sftp(args):
    """修复 SFTP subsystem：备份配置、清理主配置重复项、追加 internal-sftp、语法检查并重载。"""
    alias = args.alias

    print(f"\n{'='*60}")
    print("Remote Server Ops - 修复 SFTP subsystem")
    print(f"{'='*60}")
    print(f"别名: {alias}")
    print(f"{'='*60}\n")

    print("1️⃣ 预检当前免密 SSH ...")
    precheck = run_local_command(
        ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10', alias, 'echo SSH_OK'],
        timeout=20
    )
    if precheck.returncode != 0:
        _print_command_output("免密 SSH 未通过，停止修复", precheck)
        print(f"建议先执行: python scripts/sshctrl.py server repair-pubkey {alias} <密码>")
        return 2
    print("   ✓ 免密 SSH 可用")

    print("\n2️⃣ 备份并修复 /etc/ssh/sshd_config ...")
    remote_script = r"""
set -eu
backup="/etc/ssh/sshd_config.bak.$(date +%Y%m%d-%H%M%S)"
cp /etc/ssh/sshd_config "$backup"
tmp="$(mktemp)"
grep -vE '^[[:space:]]*Subsystem[[:space:]]+sftp([[:space:]]|$)' /etc/ssh/sshd_config > "$tmp"
printf '\nSubsystem sftp internal-sftp\n' >> "$tmp"
cat "$tmp" > /etc/ssh/sshd_config
rm -f "$tmp"
sshd -t
(systemctl reload sshd || systemctl reload ssh || systemctl restart sshd || systemctl restart ssh)
echo "backup=$backup"
sshd -T 2>/dev/null | grep -Ei 'subsystem|pubkeyauthentication|passwordauthentication|permitrootlogin' || true
"""
    result = run_local_command(['ssh', alias, remote_script], timeout=30)
    if result.returncode != 0:
        _print_command_output("SFTP 修复失败", result)
        return result.returncode
    _print_command_output("服务端修复输出", result)

    print("\n3️⃣ SFTP 回归验证 ...")
    sftp_probe = run_sftp_probe(alias, timeout=20)
    if sftp_probe.returncode == 0:
        print("   ✓ SFTP subsystem 可启动")
        return 0
    _print_command_output("SFTP 验证未通过", sftp_probe)
    print("请检查 /etc/ssh/sshd_config.d/*.conf 是否还有覆盖项，或查看 journalctl -u ssh/sshd。")
    return sftp_probe.returncode
