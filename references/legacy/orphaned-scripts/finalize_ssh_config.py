"""
SSH远控 - 完成SSH配置
修复私钥权限并在~/.ssh/config中配置SSH别名。

[强制] 此脚本必须使用SSH别名操作，不允许任何密码认证。
"""

import sys
import os
import platform
import subprocess

# 导入共享工具
try:
    from utils import validate_ip, validate_alias
except ImportError:
    print("✗ 无法导入utils模块，请确保utils.py在同一目录")
    sys.exit(1)


def main():
    if len(sys.argv) != 4:
        print("用法: python finalize_ssh_config.py <服务器IP> <用户名> <别名>")
        sys.exit(1)

    server_ip = sys.argv[1]
    username = sys.argv[2]
    alias = sys.argv[3]

    # 验证输入
    if not validate_ip(server_ip):
        print(f"✗ 无效的IP地址: {server_ip}")
        sys.exit(1)

    if not validate_alias(alias):
        print(f"✗ 无效的别名: {alias}")
        print("别名只能包含字母、数字、下划线和连字符")
        sys.exit(1)

    home = os.path.expanduser('~')
    key_name = f"id_ed25519_{server_ip.replace('.', '_')}"
    key_path = os.path.join(home, '.ssh', key_name)
    ssh_config = os.path.join(home, '.ssh', 'config')

    print(f"🔧 正在为别名 '{alias}' 完成SSH配置...")

    # 步骤1: 修复私钥权限
    print("\n1️⃣ 正在修复私钥权限...")
    if platform.system() == 'Windows':
        try:
            # 改进的Windows权限设置
            subprocess.run([
                'powershell.exe', '-NoProfile', '-Command',
                f"$path = '{key_path}'; "
                f"$acl = Get-Acl $path; "
                f"$acl.SetAccessRuleProtection($true, $false); "
                f"$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("
                f"[System.Security.Principal.WindowsIdentity]::GetCurrent().Name, "
                f"'FullControl', 'Allow'); "
                f"$acl.SetAccessRule($rule); "
                f"Set-Acl $path $acl"
            ], check=True, capture_output=True, text=True, timeout=30)
            print("✓ Windows私钥权限已修复")
        except subprocess.TimeoutExpired:
            print("⚠️  权限修复超时，尝试备用方法...")
            try:
                subprocess.run([
                    'icacls', key_path, '/inheritance:r',
                    '/grant:r', f'{os.environ.get("USERNAME")}:F'
                ], check=True, capture_output=True, timeout=15)
                print("✓ Windows私钥权限已修复（备用方法）")
            except Exception as e:
                print(f"⚠️  权限修复失败: {e}")
                print("请手动设置私钥文件权限")
        except subprocess.CalledProcessError as e:
            print(f"⚠️  权限修复失败: {e.stderr}")
    else:
        os.chmod(key_path, 0o600)
        print("✓ 私钥权限已设置为600")

    # 步骤2: 检查别名冲突
    print(f"\n2️⃣ 正在检查SSH配置冲突...")
    existing_aliases = []
    if os.path.exists(ssh_config):
        with open(ssh_config) as f:
            for line in f:
                if line.strip().startswith('Host '):
                    existing_aliases.append(line.split()[1])

    if alias in existing_aliases:
        print(f"✗ 别名 '{alias}' 已存在于 ~/.ssh/config")
        print(f"现有别名: {', '.join(existing_aliases)}")
        print("请选择一个不同的别名")
        sys.exit(1)

    # 步骤3: 追加SSH配置和保活设置
    print(f"\n3️⃣ 正在添加SSH别名 '{alias}' 及保活设置...")
    config_entry = f"""
Host {alias}
    HostName {server_ip}
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

    print(f"✓ SSH别名 '{alias}' 已配置连接保活")
    print(f"\n✅ 设置完成！测试命令: ssh {alias} \"whoami\"")


if __name__ == "__main__":
    main()
