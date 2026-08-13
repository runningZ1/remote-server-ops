"""
SSH远控 - 共享工具函数
提供所有脚本使用的通用功能。
"""

import subprocess
import sys
import os


def run_ssh_command(alias, command, capture=True, timeout=30):
    """
    通过SSH在远程服务器上执行命令。

    参数:
        alias: SSH别名
        command: 要执行的命令
        capture: 是否捕获输出
        timeout: 超时时间（秒）

    返回:
        subprocess.CompletedProcess对象
    """
    try:
        result = subprocess.run(
            ['ssh', '-o', 'ConnectTimeout=10', alias, command],
            capture_output=capture,
            text=True,
            timeout=timeout
        )
        return result
    except subprocess.TimeoutExpired:
        print(f"✗ 命令执行超时（{timeout}秒）")
        sys.exit(1)
    except Exception as e:
        print(f"✗ 命令执行失败: {e}")
        sys.exit(1)


def validate_ip(ip):
    """验证IP地址格式。"""
    import re
    pattern = r'^(\d{1,3}\.){3}\d{1,3}$'
    if not re.match(pattern, ip):
        return False
    parts = ip.split('.')
    return all(0 <= int(part) <= 255 for part in parts)


def validate_domain(domain):
    """验证域名格式。"""
    import re
    pattern = r'^([a-z0-9]+(-[a-z0-9]+)*\.)+[a-z]{2,}$'
    return re.match(pattern, domain.lower()) is not None


def validate_alias(alias):
    """验证SSH别名格式。"""
    import re
    pattern = r'^[a-zA-Z0-9_-]+$'
    return re.match(pattern, alias) is not None


def detect_package_manager(alias):
    """
    检测远程服务器的包管理器。

    返回:
        'apt', 'yum', 'dnf', 'pacman' 或 None
    """
    managers = {
        'apt-get': 'apt',
        'yum': 'yum',
        'dnf': 'dnf',
        'pacman': 'pacman'
    }

    for cmd, name in managers.items():
        result = run_ssh_command(alias, f'command -v {cmd}', timeout=10)
        if result.returncode == 0:
            return name

    return None


def install_package(alias, package_name):
    """
    使用检测到的包管理器安装软件包。

    返回:
        成功返回True，失败返回False
    """
    pm = detect_package_manager(alias)

    if pm is None:
        print("✗ 无法检测包管理器")
        return False

    print(f"📦 使用 {pm} 安装 {package_name}...")

    install_commands = {
        'apt': f'apt-get update -qq && apt-get install -y {package_name}',
        'yum': f'yum install -y {package_name}',
        'dnf': f'dnf install -y {package_name}',
        'pacman': f'pacman -S --noconfirm {package_name}'
    }

    command = install_commands.get(pm)
    if not command:
        return False

    result = run_ssh_command(alias, command, capture=False, timeout=120)
    return result.returncode == 0


def get_user_home(alias, username):
    """
    动态获取远程用户的家目录。

    返回:
        家目录路径字符串
    """
    result = run_ssh_command(alias, f'eval echo ~{username}', timeout=10)
    if result.returncode == 0:
        return result.stdout.strip()

    # 回退到默认路径
    return '/root' if username == 'root' else f'/home/{username}'


def confirm_action(prompt, default=False):
    """
    请求用户确认操作。

    参数:
        prompt: 提示信息
        default: 默认值（True/False）

    返回:
        用户确认返回True，否则返回False
    """
    suffix = " [Y/n]: " if default else " [y/N]: "
    while True:
        response = input(prompt + suffix).strip().lower()
        if response == '':
            return default
        if response in ['y', 'yes']:
            return True
        if response in ['n', 'no']:
            return False
        print("请输入 y 或 n")


def check_command_exists(alias, command):
    """
    检查远程服务器上是否存在某个命令。

    返回:
        存在返回True，否则返回False
    """
    result = run_ssh_command(alias, f'command -v {command}', timeout=10)
    return result.returncode == 0


def wait_for_service(alias, service_name, max_attempts=10, interval=2):
    """
    等待服务启动完成。

    参数:
        alias: SSH别名
        service_name: 服务名称
        max_attempts: 最大尝试次数
        interval: 检查间隔（秒）

    返回:
        服务启动成功返回True，否则返回False
    """
    import time

    for attempt in range(max_attempts):
        result = run_ssh_command(
            alias,
            f'systemctl is-active {service_name}',
            timeout=10
        )
        if result.returncode == 0 and 'active' in result.stdout:
            return True

        if attempt < max_attempts - 1:
            time.sleep(interval)

    return False
