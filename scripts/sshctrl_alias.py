#!/usr/bin/env python3
import glob
import os
import re
import subprocess
import sys


def parse_ssh_config(config_path):
    """
    解析 SSH config 文件，返回块列表。
    每块: {alias, aliases, hostname, host, port, user, identityfile}
    """
    blocks = []
    if not os.path.exists(config_path):
        return blocks

    current = None
    with open(config_path, encoding='utf-8', errors='ignore') as f:
        for raw in f:
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue

            # 处理 Include 指令（递归）
            if stripped.lower().startswith('include '):
                inc = stripped.split(None, 1)[1].strip()
                inc_path = os.path.expanduser(inc)
                if not os.path.isabs(inc_path):
                    inc_path = os.path.join(os.path.dirname(config_path), inc_path)
                # 展开通配符
                import glob as _glob
                for p in _glob.glob(inc_path):
                    blocks.extend(parse_ssh_config(p))
                current = None
                continue

            if stripped.lower().startswith('host '):
                if current:
                    blocks.append(current)
                aliases = stripped.split()[1:]
                real = [a for a in aliases if not any(c in a for c in ['*', '?'])]
                primary = real[0] if real else (aliases[0] if aliases else None)
                current = {
                    'aliases': real,
                    'alias': primary,
                    'hostname': None,
                    'host': None,
                    'port': None,
                    'user': None,
                    'identityfile': None,
                }
                continue

            if current is None:
                continue

            m = re.match(r'^\s*([A-Za-z][A-Za-z0-9-]*)\s+(.+?)\s*$', stripped)
            if not m:
                continue
            key = m.group(1).lower()
            val = m.group(2).strip()
            if key not in ('hostname', 'host', 'port', 'user', 'identityfile'):
                continue
            if val.startswith('~'):
                val = os.path.expanduser(val)
            current[key] = val

        if current:
            blocks.append(current)
    return blocks


def find_alias_exact(target, config_path=None):
    """
    精确匹配：target 必须是已配置的 HostName / 别名 本身。
    返回第一个匹配的 block。
    """
    config_path = config_path or os.path.join(os.path.expanduser('~'), '.ssh', 'config')
    blocks = parse_ssh_config(config_path)
    t = target.strip()
    t_l = t.lower()
    for b in blocks:
        if not b.get('alias'):
            continue
        if t in b.get('aliases', []):
            return b
        host = (b.get('hostname') or b.get('host') or '')
        if host.lower() == t_l:
            return b
    return None


def find_alias_fuzzy(target, config_path=None):
    """
    模糊匹配：target 是 IP/域名/别名前缀。
    返回所有候选（按匹配质量排序）。
    """
    config_path = config_path or os.path.join(os.path.expanduser('~'), '.ssh', 'config')
    blocks = parse_ssh_config(config_path)
    t = target.strip().lower()
    exact_alias, exact_host, prefix_alias, contains = [], [], [], []

    for b in blocks:
        if not b.get('alias'):
            continue
        alias_l = b['alias'].lower()
        host_l = (b.get('hostname') or b.get('host') or '').lower()
        if alias_l == t:
            exact_alias.append(b)
        elif host_l == t:
            exact_host.append(b)
        elif alias_l.startswith(t):
            prefix_alias.append(b)
        elif t in alias_l or t in host_l:
            contains.append(b)
    return exact_alias + exact_host + prefix_alias + contains


def format_alias_block(b):
    """把 block 格式化成单行可读输出。"""
    alias = b.get('alias') or '?'
    host = b.get('hostname') or b.get('host') or '?'
    port = b.get('port') or '22'
    user = b.get('user') or '?'
    return f"{alias}\thost={host}\tport={port}\tuser={user}"


def cmd_find(args):
    """
    查找 host 对应的别名（输出机器可读格式）。

    输出协议:
      ALIAS_EXACT:<alias>:<host>:<port>:<user>
      ALIAS_FUZZY:<alias>:<host>:<port>:<user>
      ALIAS_NONE:<target>
    """
    target = args.target
    config_path = os.path.join(os.path.expanduser('~'), '.ssh', 'config')

    # 1) 精确匹配
    b = find_alias_exact(target, config_path)
    if b:
        print(f"ALIAS_EXACT:{b['alias']}:{b.get('hostname') or b.get('host', '')}:"
              f"{b.get('port') or 22}:{b.get('user') or ''}")
        return 0

    # 2) 模糊匹配
    cands = find_alias_fuzzy(target, config_path)
    if cands:
        b = cands[0]
        print(f"ALIAS_FUZZY:{b['alias']}:{b.get('hostname') or b.get('host', '')}:"
              f"{b.get('port') or 22}:{b.get('user') or ''}")
        if len(cands) > 1:
            others = ', '.join(c['alias'] for c in cands[1:])
            print(f"# 其他候选: {others}", file=sys.stderr)
        return 0

    # 3) 找不到
    print(f"ALIAS_NONE:{target}")
    print(f"# 未在 ~/.ssh/config 中找到 {target} 对应的别名", file=sys.stderr)
    return 1


def cmd_connect(args):
    """
    智能连接入口：自动找别名 + 验证免密。

    输出协议:
      USING_ALIAS=<alias>          # 成功，stdout 最后一行
      AUTH_FAILED:<alias>:<reason> # 别名存在但免密失败
      NO_ALIAS:<target>            # 找不到任何别名，需要引导配置
    """
    target = args.target
    config_path = os.path.join(os.path.expanduser('~'), '.ssh', 'config')

    # 1) 精确 + 模糊匹配
    b = find_alias_exact(target, config_path)
    match_type = 'exact' if b else None
    if not b:
        cands = find_alias_fuzzy(target, config_path)
        if cands:
            b = cands[0]
            match_type = 'fuzzy'

    if b:
        alias = b['alias']
        # 验证免密
        verify = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
             alias, 'echo "AUTH_OK"'],
            capture_output=True, text=True, timeout=15
        )
        if verify.returncode == 0 and 'AUTH_OK' in (verify.stdout or ''):
            print(f"USING_ALIAS={alias}")
            if match_type == 'fuzzy':
                print(f"# 提示: {target} -> 别名 {alias}（模糊匹配）", file=sys.stderr)
            return 0
        else:
            err = (verify.stderr or '').strip().splitlines()[-1] if verify.stderr else 'unknown'
            print(f"AUTH_FAILED:{alias}:{err}")
            print(f"# 免密失败，请执行: python scripts/sshctrl.py server repair-pubkey {alias} <密码>",
                  file=sys.stderr)
            return 2

    # 2) 找不到
    print(f"NO_ALIAS:{target}")
    print(f"# 该 host 尚未配置 SSH 别名", file=sys.stderr)
    print(f"# 请提供 用户名 + 密码 后执行：", file=sys.stderr)
    print(f"#   python scripts/sshctrl.py server add {target} <用户名> <密码> <别名>",
          file=sys.stderr)
    return 3
