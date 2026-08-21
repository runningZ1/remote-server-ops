# Remote Server Ops

[![GitHub stars](https://img.shields.io/github/stars/runningZ1/remote-server-ops?style=flat-square)](https://github.com/runningZ1/remote-server-ops/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/runningZ1/remote-server-ops?style=flat-square)](https://github.com/runningZ1/remote-server-ops/commits/master)
[![Open issues](https://img.shields.io/github/issues/runningZ1/remote-server-ops?style=flat-square)](https://github.com/runningZ1/remote-server-ops/issues)

[中文](README.md) · [English](README.en.md)

**为人和 AI Agent 设计的、别名优先的远程 Linux 运维工具。** 它把一次性密码接入，收敛为可复用、可审计的 OpenSSH 别名；随后使用原生 `ssh`、`scp`、`rsync` 与 `sftp` 完成日常工作。CLI 还覆盖 SSH/SFTP 分层诊断、公钥修复、最小权限协作者账号、GitHub Deploy Key 部署和公网 IP HTTPS。

> [!IMPORTANT]
> 这不是又一个 SSH 客户端。它解决的是“把一台陌生服务器安全地接入本机工作流，并避免以后反复用密码和 IP 地址操作”的问题。

> [!NOTE]
> 项目原名为 `ssh-remote-control`，现已更名为 `remote-server-ops`；旧 GitHub 链接会自动跳转。

## 目录

- [适用场景](#适用场景)
- [核心能力](#核心能力)
- [3 分钟快速开始](#3-分钟快速开始)
- [日常工作流](#日常工作流)
- [命令速查](#命令速查)
- [安全模型](#安全模型)
- [常见问题与排障](#常见问题与排障)
- [AI Agent 使用方式](#ai-agent-使用方式)
- [深入文档](#深入文档)
- [参与贡献](#参与贡献)

## 适用场景

使用本项目，当需要：

- 首次接入 VPS、云主机或自管 Linux 服务器，并建立稳定的 SSH 密钥登录；
- 将 IP、域名或模糊项目名解析为本机 `~/.ssh/config` 中的 SSH 别名；
- 诊断 `Permission denied`、主机密钥变更、握手失败或 SFTP subsystem 启动失败；
- 在不共享 root 密码、管理员私钥或管理员别名的前提下，为协作者创建受限账号；
- 通过 GitHub Deploy Key 将私有仓库部署到服务器，或为公网裸 IP 配置可信 HTTPS；
- 把已部署的站点绑定到自有域名（DNS 托管在 Cloudflare），创建子域名并签发证书；
- 让 Agent 先解析目标主机和安全边界，再执行远程操作。

不适用于 Ansible/Terraform 机群编排、Windows RDP，或完全没有 SSH 通道的云控制台操作。

## 核心能力

| 能力 | 解决的问题 | 主要入口 |
| --- | --- | --- |
| 别名解析与连接验证 | 不再猜测 SSH 配置，也不再在已有别名时直连 IP | `connect`、`find` |
| 安全接入 | 用一次密码配置密钥认证与本地 SSH 别名 | `server add` |
| 分层诊断 | 区分网络、监听、握手、认证与 SFTP 子系统问题 | `server diagnose` |
| 定向修复 | 修复公钥认证或 SFTP，不把“能连上”误当“已修好” | `repair-pubkey`、`repair-sftp` |
| 协作者最小权限 | 按角色创建独立 Linux 账号，不共享管理员访问权 | `add-collaborator` |
| 部署与 HTTPS 指南 | 为 Deploy Key、长任务、Nginx/ACME、Cloudflare 域名绑定提供经过约束的流程 | `references/` |

## 3 分钟快速开始

### 1. 准备环境

需要 Python 3、`pip` 和系统 OpenSSH 客户端（`ssh`）。克隆仓库后，在仓库根目录执行：

```bash
python -m pip install -r requirements.txt
python scripts/sshctrl.py --version
```

`scripts/sshctrl.py` 是唯一 CLI 入口。`scripts/sshctrl_*.py` 是内部模块，不应单独调用或复制到根目录。

### 2. 已有 SSH 别名：先解析并验证

```bash
python scripts/sshctrl.py connect <IP、域名、别名或别名前缀>
ssh <alias> "whoami && hostname"
```

`connect` 的结果决定下一步：

| 输出 | 下一步 |
| --- | --- |
| `USING_ALIAS=<alias>` | 使用原生 `ssh` / `scp` / `rsync` / `sftp` 操作该别名。 |
| `AUTH_FAILED:<alias>:<reason>` | 先运行 `server diagnose`，根据证据修复。 |
| `NO_ALIAS:<target>` | 明确确认主机、登录用户和有语义的别名后，执行接入。 |

### 3. 新服务器：接入一次，之后只用别名

在当前终端中以安全方式设置 `SSHCTRL_PASSWORD` 后，以 `-` 代替命令行密码参数：

```bash
python scripts/sshctrl.py server add <host> <user> - <alias> [--port N]
python scripts/sshctrl.py server diagnose <alias>
ssh -o BatchMode=yes <alias> "echo SSH_OK"
```

别名必须可读且稳定，例如 `blog-prod`、`api-aws`；不要用难以理解的 IP 作为常规名称。只有新的无交互密钥登录成功后，才视为接入完成。完整验收标准见 [接入验收](references/onboarding-acceptance.md)。

## 日常工作流

```text
解析目标 → 验证无交互密钥认证 → 原生 OpenSSH 工作 → 变更后用新会话复验
```

```bash
# 远程执行
ssh <alias> "uptime && df -h /"

# 上传、同步或进入 SFTP
scp ./release.tar.gz <alias>:/opt/releases/
rsync -avz --progress ./dist/ <alias>:/var/www/app/
sftp <alias>
```

预计超过约两分钟的构建、迁移或大文件传输应在服务器的 `tmux` 中运行。SSH keepalive 只能降低空闲断线概率，不能保证中断后的任务继续执行。参考 [长时间任务](references/long-running-tasks.md)。

## 命令速查

| 任务 | 命令 |
| --- | --- |
| 查找本地别名（不连接） | `python scripts/sshctrl.py find <target>` |
| 解析别名并验证密钥登录 | `python scripts/sshctrl.py connect <target>` |
| 接入新服务器 | `python scripts/sshctrl.py server add <host> <user> - <alias> [--port N]` |
| 查看或移除已管理服务器 | `python scripts/sshctrl.py server list` / `server remove <alias>` |
| 通过已解析别名运行命令 | `python scripts/sshctrl.py server ssh <alias> "uptime"` |
| 只读诊断 SSH/SFTP | `python scripts/sshctrl.py server diagnose <alias> [--full]` |
| 修复公钥认证 | `python scripts/sshctrl.py server repair-pubkey <alias> -` |
| 修复 SFTP subsystem | `python scripts/sshctrl.py server repair-sftp <alias>` |
| 创建受限协作者 | `python scripts/sshctrl.py server add-collaborator <alias> <user> <tier> [options]` |

运行 `python scripts/sshctrl.py --help` 获取完整参数说明。

### 协作者权限档位

| 档位 | 权限边界 | 关键参数 |
| --- | --- | --- |
| `readonly-deploy` | 一个项目属组的读写；没有通用 sudo；可选重启指定服务 | `--group`、`--restart-service` |
| `full-shell` | 普通 Shell；不加入 `sudo`、`wheel` 或 `docker` | 无 |
| `sudo-whitelist` | 仅可免密执行明确列出的绝对路径命令 | `--sudo-cmd`（必填，可重复） |
| `sftp-only` | 指定目录 chroot，只能 SFTP，不能 Shell | `--chroot-dir`（必填） |

示例与账号契约见 [协作者账号](references/collaborator-accounts.md)。

## 安全模型

本项目有意设置了以下边界：

- **别名优先。** 已有别名时，不再使用 `ssh user@ip`、`sshpass` 或密码型 Paramiko 会话进行日常运维。
- **密码只用于救援/接入。** `server add` 与 `repair-pubkey` 支持用 `-` 从 `SSHCTRL_PASSWORD` 读取密码，避免密码出现在 argv；仍应只在当前终端短暂设置并及时清除。
- **先证据、后修改。** `diagnose` 用于分层定位；不要把网络、认证和 SFTP 错误混为一谈。
- **SSH 配置变更可回退。** 修改 `sshd` 前必须备份、运行 `sshd -t`、重载服务，并在关闭当前会话前用一个新会话验证。
- **root 不是常规登录方式。** `repair-pubkey` 对 root 会设置 `PermitRootLogin prohibit-password`；生产环境应优先使用非 root 管理员账号和最小权限协作者账号。
- **不静默信任未知主机。** 主机密钥异常必须先确认真实服务器身份；不要为了“解决报错”直接忽略警告。

## 常见问题与排障

| 现象 | 首选动作 |
| --- | --- |
| `Permission denied` | `python scripts/sshctrl.py server diagnose <alias>`，确认用户、密钥、服务端策略和 `authorized_keys`。 |
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | 先带外确认服务器身份，再按提示使用 `ssh-keygen -R <host>` 更新本机记录。 |
| SSH 能登录但 SFTP/Xftp 失败 | 运行 `server repair-sftp`；不要把它误判为 SSH 认证失败。 |
| 接入后仍要求密码 | 运行 `server diagnose`，必要时执行 `repair-pubkey`，然后用 `BatchMode=yes` 复验。 |
| 远程构建中途断开 | 将任务移入 `tmux`，通过 `capture-pane` 读取进度。 |

完整的证据命令、错误分层和修复边界见 [SSH / SFTP 分层排障](references/ssh-sftp-troubleshooting.md)。

## AI Agent 使用方式

当 Agent 运行环境可加载本技能时，使用：

```text
Use $remote-server-ops to resolve the alias before operating on a remote Linux server.
```

技能契约在 [SKILL.md](SKILL.md)。其关键规则是先解析别名、先诊断后修复、任何 `sshd` 变更均用新会话验证；不要让 Agent 猜测别名或在日志中输出密码/私钥。

## 深入文档

| 场景 | 文档 |
| --- | --- |
| 接入完成后的验收 | [onboarding-acceptance.md](references/onboarding-acceptance.md) |
| SSH / SFTP 分层诊断与修复 | [ssh-sftp-troubleshooting.md](references/ssh-sftp-troubleshooting.md) |
| 远程执行、隧道、传输与 rsync | [ssh-commands-reference.md](references/ssh-commands-reference.md) |
| 构建、迁移等长时间任务 | [long-running-tasks.md](references/long-running-tasks.md) |
| 最小权限协作者账号 | [collaborator-accounts.md](references/collaborator-accounts.md) |
| GitHub 私有仓库 Deploy Key 部署 | [github-deploy-guide.md](references/github-deploy-guide.md) |
| 公网裸 IP 的可信 HTTPS | [ip-https-deployment.md](references/ip-https-deployment.md) |
| Cloudflare 域名/子域名绑定与证书签发 | [cloudflare-domain-binding.md](references/cloudflare-domain-binding.md) |

## 参与贡献

欢迎报告可复现的问题、补充 Linux 发行版差异、改进文档和提交小而聚焦的 Pull Request。提交前请至少运行：

```bash
python -m py_compile scripts/sshctrl.py scripts/sshctrl_alias.py scripts/sshctrl_collaborator.py scripts/sshctrl_common.py scripts/sshctrl_onboard.py scripts/sshctrl_repair.py
python scripts/sshctrl.py --help
git diff --check
```

报告问题时请移除密码、私钥、Cookie、真实 IP（如敏感）和完整 `~/.ssh/config`；提供脱敏后的命令、实际输出、预期结果、操作系统与 OpenSSH/Python 版本即可。

## 许可证与支持

> [!CAUTION]
> 当前仓库尚未包含 `LICENSE` 文件。公开可见不等于已授予复用、修改或分发许可；在许可证明确前，请勿假定拥有开源授权。

如果项目对你的服务器运维或 Agent 工作流有帮助，欢迎给仓库点 Star，并通过 Issue 分享真实场景、失败案例或文档改进建议。这些反馈会直接帮助项目向更可靠的开源工具演进。
