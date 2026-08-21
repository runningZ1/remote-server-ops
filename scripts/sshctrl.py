#!/usr/bin/env python3
import argparse
import sys

from sshctrl_alias import cmd_connect, cmd_find
from sshctrl_collaborator import COLLAB_TIERS, cmd_server_add_collaborator
from sshctrl_common import VERSION
from sshctrl_onboard import cmd_server_add, cmd_server_list, cmd_server_remove, cmd_server_ssh
from sshctrl_repair import cmd_server_diagnose, cmd_server_repair_pubkey, cmd_server_repair_sftp


def main():
    parser = argparse.ArgumentParser(
        description="SSH Remote Control - SSH免密连接配置工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
核心SOP流程（AI agent 调用）:
  1. sshctrl connect <host>           # 智能解析别名 + 验证免密
  2. sshctrl find <host>              # 仅查找别名，不连接
  3. sshctrl server add <host> <用户> <密码> <别名>   # 新服务器引导配置
  4. ssh <别名> "命令"                # 日常操作（永远用别名）

密码可用 '-' 并从环境变量 SSHCTRL_PASSWORD 读取，避免出现在 argv。

示例:
  sshctrl connect 198.44.177.126
  sshctrl find jxyg
  sshctrl server add 192.168.1.100 root - myserver
  sshctrl server add connect.nmb2.seetacloud.com root - myserver --port 20605
  sshctrl server diagnose myserver
  sshctrl server repair-pubkey myserver -
  sshctrl server repair-sftp myserver
  sshctrl server list
  sshctrl server ssh myserver "uptime"
        """
    )
    parser.add_argument('--version', action='version', version=f'sshctrl {VERSION}')

    subparsers = parser.add_subparsers(dest='command', help='可用子命令')

    # 顶层 find / connect（AI agent 默认入口）
    find_parser = subparsers.add_parser('find', help='在 ~/.ssh/config 中反查 host 对应的别名')
    find_parser.add_argument('target', help='IP / 域名 / 别名前缀')

    connect_parser = subparsers.add_parser('connect', help='智能连接：找别名 + 验证免密')
    connect_parser.add_argument('target', help='IP / 域名 / 别名')

    # server 子命令
    server_parser = subparsers.add_parser('server', help='服务器管理')
    server_subparsers = server_parser.add_subparsers(dest='server_command')

    add_parser = server_subparsers.add_parser('add', help='添加并配置新服务器')
    add_parser.add_argument('host', help='服务器主机（IP或域名）')
    add_parser.add_argument('username', help='用户名')
    add_parser.add_argument('password', help="密码，或 '-' 表示读取环境变量 SSHCTRL_PASSWORD")
    add_parser.add_argument('alias', help='SSH别名（必填，须先问用户：项目名/云厂商名优先，IP兜底）')
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
    repair_parser.add_argument('password', help="服务器密码（仅用于本次修复）；'-' 表示读取 SSHCTRL_PASSWORD")

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

    diagnose_parser = server_subparsers.add_parser(
        'diagnose',
        help='只读分层诊断 SSH 认证与 SFTP subsystem'
    )
    diagnose_parser.add_argument('alias', help='服务器别名')
    diagnose_parser.add_argument(
        '--full',
        action='store_true',
        help='即使免密 SSH 失败也继续尝试后续只读检查'
    )

    repair_sftp_parser = server_subparsers.add_parser(
        'repair-sftp',
        help='修复 SFTP subsystem 为 internal-sftp 并验证'
    )
    repair_sftp_parser.add_argument('alias', help='服务器别名')

    args = parser.parse_args()

    if args.command == 'find':
        sys.exit(cmd_find(args))
    elif args.command == 'connect':
        sys.exit(cmd_connect(args))
    elif args.command == 'server':
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
        elif args.server_command == 'diagnose':
            sys.exit(cmd_server_diagnose(args))
        elif args.server_command == 'repair-sftp':
            sys.exit(cmd_server_repair_sftp(args))
        else:
            server_parser.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

