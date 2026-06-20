# SSH Remote Control

[![GitHub](https://img.shields.io/badge/GitHub-ssh--remote--control-blue?logo=github)](https://github.com/runningZ1/ssh-remote-control)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

**核心功能**：配置SSH免密连接，AI agent 通过智能别名解析使用原生SSH命令操作远程服务器。

**GitHub**: https://github.com/runningZ1/ssh-remote-control

---

## 快速开始

### 1. 安装依赖

```bash
pip install paramiko
```

### 2. 配置免密连接（只需一次）

```bash
python sshctrl.py server add <host> <用户名> <密码> [别名] [--port 端口]
```

示例：
```bash
python sshctrl.py server add 38.76.206.12 root mypassword myserver
python sshctrl.py server add connect.nmb2.seetacloud.com root mypassword seetacloud_20605 --port 20605
```

### 3. 智能连接（AI agent 默认入口）

```bash
# 输入 host，自动在 ~/.ssh/config 里反查别名
python sshctrl.py connect <host>

# 输出:
#   USING_ALIAS=jxyg-198          ← 成功，拿到别名
#   AUTH_FAILED:...               ← 别名存在但免密失败
#   NO_ALIAS:...                  ← 没找到，需要 server add
```

### 4. 日常操作（直接用SSH命令）

```bash
# 执行命令
ssh myserver "docker ps"
ssh myserver "cd /opt/app && git pull"

# 文件传输
scp file.txt myserver:/remote/path/
scp myserver:/remote/path/file.txt ./
```

**不需要任何脚本！**

---

## 工作流程

```
┌─────────────────────────────────────────────────────┐
│  第1步：初始配置（一次性）                             │
│                                                     │
│  python sshctrl.py server add <IP> <用户> <密码>     │
│                                                     │
│  这个命令：                                         │
│  1. 测试密码连接                                    │
│  2. 生成SSH密钥                                     │
│  3. 上传公钥到服务器                                 │
│  4. 配置本地SSH别名                                  │
│  5. 验证免密连接                                    │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│  第2步：日常操作（直接用原生SSH命令）                 │
│                                                     │
│  ssh <别名> "命令"                                  │
│  scp file.txt <别名>:/path/                          │
│                                                     │
│  不需要任何脚本！                                     │
└─────────────────────────────────────────────────────┘
```

---

## sshctrl 命令

```bash
# 配置服务器免密连接
python sshctrl.py server add <host> <用户名> <密码> [别名] [--port 端口]

# 列出已配置服务器
python sshctrl.py server list

# 移除服务器配置
python sshctrl.py server remove <别名>

# SSH连接
python sshctrl.py server ssh <别名> [命令]

# 自动修复服务端公钥认证（当免密失败时）
python sshctrl.py server repair-pubkey <别名> <密码>
```

## 完整成功流程（推荐SOP）

```bash
# 1) 一次性配置免密
python sshctrl.py server add <host> <用户名> <密码> <别名> [--port 端口]

# 2) 如果免密失败，自动修复服务端公钥认证
python sshctrl.py server repair-pubkey <别名> <密码>

# 3) 最终验收（必须无交互成功）
ssh -o BatchMode=yes <别名> "whoami && hostname"
```

---

## SSH 常用命令

### 执行命令

```bash
ssh <别名> "uname -a"
ssh <别名> "df -h"
ssh <别名> "free -h"
ssh <别名> "systemctl status nginx"
ssh <别名> "docker ps"
```

### 文件传输（推荐 rsync）

rsync 是传输文件/目录的最佳工具，支持增量传输、断点续传、压缩传输、保留属性和进度显示。

```bash
# 上传单个文件
rsync -avz --progress local_file.txt <别名>:/remote/path/

# 上传整个目录（推荐）
rsync -avz --progress local_dir/ <别名>:/remote/path/

# 大文件推荐加 --partial 支持断点续传
rsync -avz --partial --progress large_file.zip <别名>:/remote/path/

# 非默认SSH端口
rsync -avz -e "ssh -p 2222" local_dir/ <别名>:/remote/path/

# 下载文件
rsync -avz --progress <别名>:/remote/path/file.txt ./
rsync -avz --progress <别名>:/remote/path/folder/ ./local/folder/
```

**rsync 优势**：比 scp 更智能，只传输变化的部分（增量传输），节省时间和流量。几乎所有 Linux/macOS 都预装。

### 备选：SFTP reget（rsync 不可用时）

当 rsync 未安装或安装失败时，使用 OpenSSH SFTP 命令：

```bash
# 上传文件
sftp <别名> << 'EOF'
put local_file.txt /remote/path/
put -r local_dir/ /remote/path/
EOF

# 断点续传下载（reget 自动支持）
sftp <别名> << 'EOF'
reget /remote/path/large_file.zip
EOF
```

### 备选 scp（简单场景）

```bash
# 上传
scp local_file.txt <别名>:/remote/path/
scp -r local_dir/ <别名>:/remote/path/

# 下载
scp <别名>:/remote/path/file.txt ./
scp -r <别名>:/remote/path/dir/ ./
```

---

## 故障排除

### `REMOTE HOST IDENTIFICATION HAS CHANGED`

```bash
ssh-keygen -R <服务器IP>
```

### 免密连接失败

```bash
# 检查别名配置
cat ~/.ssh/config | grep -A 10 <别名>

# 测试连接
ssh -v <别名> "whoami"
```

### `server add` 显示完成，但 `ssh <别名>` 仍失败

这通常不是脚本问题，而是服务端认证策略问题。优先检查：

```bash
# 1) 客户端诊断：确认公钥认证是否被服务端接受
ssh -vvv -o BatchMode=yes <别名> "echo ok"

# 2) 服务端诊断：查看SSH认证策略（在服务器本机执行）
sshd -T | grep -E 'pubkeyauthentication|passwordauthentication|authorizedkeysfile'
```

如果输出 `pubkeyauthentication no`，说明服务端禁用了公钥认证。需要在 `sshd_config` 中开启后重载 `sshd`。

可直接执行自动修复：

```bash
python sshctrl.py server repair-pubkey <别名> <密码>
```

### 首次连通过程卡住或超时

常见原因是 SSH 在等待交互（指纹确认/密码输入），可用批处理模式快速识别：

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 <别名> "echo ok"
```

若提示 `Permission denied (password)`，表示当前仍在密码认证路径，免密未生效。

### 私钥权限错误

```bash
# Linux/Mac
chmod 600 ~/.ssh/id_ed25519_*

# Windows - 重新运行配置
python sshctrl.py server add <host> <用户> <密码> [别名] [--port 端口]
```

### Windows 特殊情况：权限修复失败

`sshctrl.py` 在 Windows 上会尝试自动修复私钥 ACL；若出现 `权限修复失败`，建议：

1. 确认私钥文件存在：`~/.ssh/id_ed25519_<ip>`
2. 重新运行 `server add` 并观察 `ssh -vvv -o BatchMode=yes <别名> "echo ok"` 的认证日志
3. 若日志显示已发送公钥但服务端拒绝，优先排查服务端 `PubkeyAuthentication`

### 同一IP重装或迁移后无法连接

当服务器重装或更换主机密钥时，必须清理本地旧指纹：

```bash
ssh-keygen -R <服务器IP>
```

然后重新连接一次，让新指纹写入 `known_hosts`。

---

## 参考资料

- `references/ssh-commands-reference.md` - SSH命令完整参考
- `references/detailed-guide.md` - 详细指南和故障排除
- `SKILL.md` - 代理操作手册

---

## 安全说明

配置完成后：
- 密码不会保存
- 所有操作使用SSH密钥免密执行
- 建议在服务器上禁用密码认证

---

## 调用策略（避免错误调用形式）

适用于在其他项目中调用本技能时，防止退回 `python <<'PYEOF' + paramiko` 形式。

### 强制规则

1. 首次引导阶段，最多允许一次：
   `python sshctrl.py server add ...`
2. 后续所有远程执行只允许：
   `ssh <别名> "命令"`、`scp ...`
3. 禁止：
   `python <<'PYEOF'`、`paramiko`、`sshpass`、任何明文密码远控脚本

### 推荐任务前置语句

```text
使用 $ssh-remote-control 技能。
禁止 python<<PYEOF、paramiko、sshpass。
只用 ssh/scp：ssh <alias> "<command>"。
```

### 出现偏航时的纠正语句

```text
停止当前实现。你违反了远程执行策略。
重新执行：仅使用 `ssh <alias> "<command>"`。
```

---

**最后更新**: 2026-04-30
