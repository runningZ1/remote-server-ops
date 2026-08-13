"""
SSH远控 - 上传SSH密钥
此脚本仅用于初始配置阶段（将公钥上传到authorized_keys）。
配置完成后，后续所有操作必须使用SSH别名免密执行，禁止使用密码认证。
"""

import sys
import os
import paramiko

# 导入共享工具
try:
    from utils import validate_ip
except ImportError:
    print("✗ 无法导入utils模块，请确保utils.py在同一目录")
    sys.exit(1)


def main():
    if len(sys.argv) != 4:
        print("用法: python upload_ssh_key.py <服务器IP> <用户名> <密码>")
        sys.exit(1)

    server_ip = sys.argv[1]
    username = sys.argv[2]
    password = sys.argv[3]

    # 验证IP地址格式
    if not validate_ip(server_ip):
        print(f"✗ 无效的IP地址: {server_ip}")
        sys.exit(1)

    home = os.path.expanduser('~')
    key_name = f"id_ed25519_{server_ip.replace('.', '_')}"
    pubkey_path = os.path.join(home, '.ssh', key_name + '.pub')

    if not os.path.exists(pubkey_path):
        print(f"✗ 未找到公钥: {pubkey_path}")
        print("请先运行 generate_ssh_key.py")
        sys.exit(1)

    with open(pubkey_path) as f:
        pubkey = f.read().strip()

    print(f"📤 正在上传公钥到 {username}@{server_ip}...")

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(server_ip, username=username, password=password, timeout=10)

        # 动态获取用户家目录
        stdin, stdout, stderr = ssh.exec_command(f'eval echo ~{username}')
        user_home = stdout.read().decode().strip()

        if not user_home or user_home == '':
            # 回退到默认路径
            user_home = '/root' if username == 'root' else f'/home/{username}'
            print(f"⚠️  使用默认家目录: {user_home}")
        else:
            print(f"✓ 检测到家目录: {user_home}")

        ssh_dir = f'{user_home}/.ssh'
        ssh.exec_command(f'mkdir -p {ssh_dir} && chmod 700 {ssh_dir}')

        # 通过SFTP上传密钥（避免shell转义问题）
        sftp = ssh.open_sftp()
        auth_keys_path = f'{ssh_dir}/authorized_keys'

        try:
            with sftp.open(auth_keys_path, 'a') as f:
                f.write(pubkey + '\n')
            sftp.chmod(auth_keys_path, 0o600)
            print(f"✓ 公钥已上传到 {auth_keys_path}")
        except Exception as e:
            print(f"✗ 上传失败: {e}")
            sys.exit(1)
        finally:
            sftp.close()

        # 验证密钥指纹
        stdin, stdout, stderr = ssh.exec_command(f'ssh-keygen -lf {auth_keys_path} | tail -1')
        fingerprint = stdout.read().decode().strip()
        print(f"🔐 密钥指纹: {fingerprint}")

        ssh.close()
        print("\n✅ 上传完成")

    except Exception as e:
        print(f"✗ 连接失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
