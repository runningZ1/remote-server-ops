"""
SSH远控 - 设置SSH认证
此脚本仅用于初始配置阶段（建立密码连接并启用公钥认证）。
配置完成后，后续所有操作必须使用SSH别名免密执行，禁止使用密码认证。
"""

import sys
import paramiko
import time

# 导入共享工具
try:
    from utils import validate_ip, install_package, check_command_exists, wait_for_service
except ImportError:
    print("✗ 无法导入utils模块，请确保utils.py在同一目录")
    sys.exit(1)


def backup_sshd_config(ssh):
    """备份sshd配置文件。"""
    backup_path = f'/etc/ssh/sshd_config.backup.{int(time.time())}'
    stdin, stdout, stderr = ssh.exec_command(
        f'sudo cp /etc/ssh/sshd_config {backup_path}'
    )
    stdout.channel.recv_exit_status()
    return backup_path


def test_sshd_config(ssh):
    """测试sshd配置是否有效。"""
    stdin, stdout, stderr = ssh.exec_command('sudo sshd -t')
    exit_status = stdout.channel.recv_exit_status()
    return exit_status == 0


def enable_pubkey_auth(ssh):
    """启用公钥认证并安全地重启sshd。"""
    print("⚠️  公钥认证已禁用，正在启用...")

    # 备份配置
    print("  正在备份sshd配置...")
    backup_path = backup_sshd_config(ssh)
    print(f"  ✓ 配置已备份到: {backup_path}")

    # 修改配置
    print("  正在修改配置...")
    stdin, stdout, stderr = ssh.exec_command(
        "sudo sed -i 's/^PubkeyAuthentication no/PubkeyAuthentication yes/' /etc/ssh/sshd_config && "
        "sudo sed -i 's/^#PubkeyAuthentication yes/PubkeyAuthentication yes/' /etc/ssh/sshd_config"
    )
    stdout.channel.recv_exit_status()

    # 测试配置
    print("  正在测试配置...")
    if not test_sshd_config(ssh):
        print("  ✗ 配置测试失败，正在回滚...")
        ssh.exec_command(f'sudo cp {backup_path} /etc/ssh/sshd_config')
        return False

    print("  ✓ 配置测试通过")

    # 重启sshd
    print("  正在重启sshd...")
    stdin, stdout, stderr = ssh.exec_command('sudo systemctl restart sshd')
    stdout.channel.recv_exit_status()

    # 等待服务启动
    time.sleep(3)

    # 验证服务状态
    stdin, stdout, stderr = ssh.exec_command('sudo systemctl is-active sshd')
    status = stdout.read().decode().strip()

    if status != 'active':
        print("  ✗ sshd重启失败，正在回滚...")
        ssh.exec_command(f'sudo cp {backup_path} /etc/ssh/sshd_config')
        ssh.exec_command('sudo systemctl restart sshd')
        return False

    print("  ✓ 公钥认证已启用，sshd已重启")
    return True


def main():
    if len(sys.argv) != 4:
        print("用法: python setup_ssh_auth.py <服务器IP> <用户名> <密码>")
        sys.exit(1)

    server_ip = sys.argv[1]
    username = sys.argv[2]
    password = sys.argv[3]

    # 验证IP地址
    if not validate_ip(server_ip):
        print(f"✗ 无效的IP地址: {server_ip}")
        sys.exit(1)

    print(f"🔗 正在连接到 {username}@{server_ip}...")

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server_ip, username=username, password=password, timeout=10)
        print("✓ 连接成功")

        # 检查sshd配置
        stdin, stdout, stderr = ssh.exec_command('sshd -T | grep pubkeyauth')
        config = stdout.read().decode().strip()
        print(f"\n📋 当前SSH配置: {config}")

        if 'pubkeyauthentication no' in config.lower():
            if not enable_pubkey_auth(ssh):
                print("✗ 启用公钥认证失败")
                sys.exit(1)
        else:
            print("✓ 公钥认证已启用")

        # 获取服务器信息
        stdin, stdout, stderr = ssh.exec_command('uname -a && hostname')
        server_info = stdout.read().decode().strip()
        print(f"\n🖥️  服务器信息:\n{server_info}")

        # 安装tmux以保持会话持久性
        print("\n📦 正在检查tmux...")
        stdin, stdout, stderr = ssh.exec_command('command -v tmux')
        if stdout.read().decode().strip():
            print("✓ tmux已安装")
        else:
            print("正在安装tmux...")

            # 直接在当前paramiko会话中检测包管理器并安装
            managers = {
                'apt-get': 'apt',
                'yum': 'yum',
                'dnf': 'dnf',
                'pacman': 'pacman'
            }
            pm = None
            for cmd, name in managers.items():
                stdin, stdout, stderr = ssh.exec_command(f'command -v {cmd}')
                if stdout.read().decode().strip():
                    pm = name
                    break

            if pm == 'apt':
                cmd = 'sudo apt-get update -qq && sudo apt-get install -y tmux'
            elif pm == 'yum':
                cmd = 'sudo yum install -y tmux'
            elif pm == 'dnf':
                cmd = 'sudo dnf install -y tmux'
            elif pm == 'pacman':
                cmd = 'sudo pacman -S --noconfirm tmux'
            else:
                print("⚠️  无法检测包管理器，跳过tmux安装")
                cmd = None

            if cmd:
                stdin, stdout, stderr = ssh.exec_command(cmd)
                stdout.channel.recv_exit_status()
                time.sleep(2)

                stdin, stdout, stderr = ssh.exec_command('command -v tmux')
                if stdout.read().decode().strip():
                    print("✓ tmux安装成功")
                else:
                    print("⚠️  tmux安装失败（非关键，但建议手动安装）")

        ssh.close()
        print("\n✅ 设置完成")

    except paramiko.AuthenticationException:
        print("✗ 认证失败，请检查用户名和密码。")
        sys.exit(1)
    except paramiko.SSHException as e:
        print(f"✗ SSH错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"✗ 连接失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
