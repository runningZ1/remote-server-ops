# SSH Remote Control

[中文](README.md) · [English](README.en.md)

面向 Agent 的 **别名优先** Linux SSH 技能：密钥接入、分层诊断、公钥/SFTP 修复、受限协作者账号，以及按需做公网 IP 的 HTTPS。

接入完成后，日常只用原生 OpenSSH：

```bash
python scripts/sshctrl.py connect <host-or-alias>
ssh <alias> "whoami && hostname"
```

## 不覆盖

- Ansible / Terraform / 机群编排
- Windows 远程桌面
- 只有云控制台、没有 SSH 路径的场景

## 安装

```bash
pip install -r requirements.txt
python scripts/sshctrl.py --version
```

CLI 入口只有 `scripts/sshctrl.py`，同目录下的 `sshctrl_*.py` 是拆开的辅助脚本。不要在技能根目录再放一份。

## 安全说明

- `server add` / `repair-pubkey` 的密码参数可用 `-`，从环境变量 `SSHCTRL_PASSWORD` 读取，避免出现在命令行。
- 对 root 执行 `repair-pubkey` 会把 `PermitRootLogin` 设为 `prohibit-password`。
- 未知主机密钥会告警，不再静默自动加入。

Agent 契约见 `SKILL.md`。
