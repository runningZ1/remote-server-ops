"""
SSH远控 - 生成SSH密钥
为服务器认证创建一个无密码的Ed25519 SSH密钥对。

[强制] 此脚本必须使用SSH别名操作，不允许任何密码认证。
"""

import sys
import os
import subprocess

# 导入共享工具
try:
    from utils import validate_ip, confirm_action
except ImportError:
    print("✗ 无法导入utils模块，请确保utils.py在同一目录")
    sys.exit(1)


def main():
    if len(sys.argv) < 2:
        print("用法: python generate_ssh_key.py <服务器IP> [--force]")
        print("\n选项:")
        print("  --force    不询问直接覆盖已存在的密钥")
        sys.exit(1)

    server_ip = sys.argv[1]
    force = '--force' in sys.argv

    # 验证IP地址格式
    if not validate_ip(server_ip):
        print(f"✗ 无效的IP地址: {server_ip}")
        sys.exit(1)

    home = os.path.expanduser('~')
    key_name = f"id_ed25519_{server_ip.replace('.', '_')}"
    key_path = os.path.join(home, '.ssh', key_name)

    print(f"🔑 正在生成SSH密钥: {key_name}")

    # 检查旧密钥并请求确认
    existing_keys = []
    for path in [key_path, key_path + '.pub']:
        if os.path.exists(path):
            existing_keys.append(os.path.basename(path))

    if existing_keys:
        print(f"\n⚠️  发现已存在的密钥:")
        for key in existing_keys:
            print(f"  - {key}")

        if not force:
            if not confirm_action("\n是否删除并重新生成密钥？", default=False):
                print("操作已取消")
                sys.exit(0)

        # 删除旧密钥
        for path in [key_path, key_path + '.pub']:
            if os.path.exists(path):
                os.remove(path)
                print(f"  已删除旧密钥: {os.path.basename(path)}")

    # 生成新的无密码密钥
    result = subprocess.run(
        ['ssh-keygen', '-t', 'ed25519', '-f', key_path, '-N', '', '-C', f'claude-code-{server_ip}'],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        print(f"✓ 密钥生成成功")
        with open(key_path + '.pub') as f:
            pubkey = f.read().strip()
            print(f"\n📄 公钥:\n{pubkey}")
    else:
        print(f"✗ 密钥生成失败:\n{result.stderr}")
        sys.exit(1)


if __name__ == "__main__":
    main()
