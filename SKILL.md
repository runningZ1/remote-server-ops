---
name: ssh-remote-control
description: SSH远控技能 - 配置SSH免密连接后，使用原生SSH命令操作远程服务器。
---

# SSH远控 - 代理操作手册

## 概述

建立与远程服务器的SSH免密验证连接。配置完成后，日常操作直接使用原生SSH命令，无需任何脚本。

## 核心原则

**配置免密一次，后续操作只用 `ssh <别名> "命令"`**

---

## 🔴 强制规则：免密操作

### 唯一可用方式
| 阶段 | 操作方式 |
|------|----------|
| 初始配置 | `sshctrl.py server add <host> <用户> <密码> [别名] [--port 端口]` |
| 日常操作 | `ssh <别名> "命令"` |

### 禁止方式
```
❌ python script.py <别名> <命令>     # 禁止用脚本执行
❌ sshpass -p 'pass' ssh <别名>        # 禁止用密码
❌ paramiko + password                # 禁止用密码认证
❌ python <<'PYEOF' ... paramiko ...  # 禁止heredoc内联远控
```

### 为什么
1. **安全**：密码不出现在日志、历史记录
2. **简洁**：直接用系统SSH命令，不依赖脚本
3. **可靠**：SSH客户端已是最优实现

---

## ⚠️ 配置前必须检查（重要）

**在执行 `server add` 之前，必须先检查服务器是否已配置！**

### 为什么要先检查

已配置的服务器会优先使用密钥认证，导致：
1. 密码认证失败（即使密码正确）
2. `sshctrl.py server add` 报错"认证失败"
3. paramiko 密码连接失败

### 检查步骤

```bash
# 1. 检查是否已有该服务器的配置
cat ~/.ssh/config | grep -B 1 "HostName <IP>"

# 2. 如果找到配置，会显示类似：
# Host <别名>
#     HostName <IP>

# 3. 测试已存在的别名
ssh <别名> "whoami && hostname"

# 4. 如果连接成功，直接使用该别名，无需重新配置
```

### 快速检查命令

```bash
# 一键检查并测试（替换 <IP> 为实际IP）
alias=$(cat ~/.ssh/config | grep -B 1 "HostName <IP>" | grep "^Host " | awk '{print $2}') && \
if [ -n "$alias" ]; then \
  echo "找到别名: $alias" && \
  ssh -o ConnectTimeout=10 "$alias" "echo '✓ 连接成功'" && \
  echo "可直接使用: ssh $alias \"命令\""; \
else \
  echo "未找到配置，可以执行 server add"; \
fi
```

### 示例：检查 198.44.177.126

```bash
$ cat ~/.ssh/config | grep -B 1 "HostName 198.44.177.126"
Host jxyg-198
    HostName 198.44.177.126

$ ssh jxyg-198 "whoami && hostname"
root
ser117937227725

# ✓ 服务器已配置，别名是 jxyg-198，直接使用即可
```

---

## 初始配置SOP

**前提**：
1. 用户提供 host（IP或域名）、用户名、密码（可选端口）
2. **已确认该服务器未配置**（参考上面的检查步骤）

**执行**：
```bash
python sshctrl.py server add <host> <用户名> <密码> [别名] [--port 端口]
```

示例（非22端口）：
```bash
python sshctrl.py server add connect.nmb2.seetacloud.com root <密码> seetacloud_20605 --port 20605
```

**这个命令做了什么**（透明化流程）：
1. 测试密码SSH连接
2. 生成Ed25519 SSH密钥对
3. 上传公钥到服务器的 `~/.ssh/authorized_keys`
4. 配置本地 `~/.ssh/config` 添加别名和保活参数
5. **验证免密连接是否成功**

**完成后输出**：
```
✅ 服务器配置完成！
验证命令: ssh <别名> "whoami && hostname"
```

---

## 日常操作（配置完成后）

**直接使用原生SSH命令**：
```bash
# 执行命令
ssh <别名> "docker ps"
ssh <别名> "cd /opt/app && git pull && npm install"

# 文件传输（推荐 rsync）
rsync 是传输文件/目录的最佳工具，支持增量传输、断点续传、压缩传输、保留属性和进度显示。

```bash
# 传输单个文件
rsync -avz --progress local_file.txt <别名>:/remote/path/

# 传输整个目录（推荐）
rsync -avz --progress local_dir/ <别名>:/remote/path/

# 大文件推荐加上 --partial 支持断点续传
rsync -avz --partial --progress large_file.txt <别名>:/remote/path/

# 非默认SSH端口
rsync -avz -e "ssh -p 2222" local_dir/ <别名>:/remote/path/

# 下载文件
rsync -avz --progress <别名>:/remote/path/file.txt ./
rsync -avz --progress <别名>:/remote/path/folder/ ./local/folder/
```

**rsync 优势**：比 scp 更智能，只传输变化的部分（增量传输），节省时间和流量。适合大文件或目录同步。

**备选：SFTP reget**（当 rsync 未安装或安装失败时）
```bash
# 上传
sftp <别名> << 'EOF'
put local_file.txt /remote/path/
put -r local_dir/ /remote/path/
EOF

# 断点续传下载（大文件推荐）
sftp <别名> << 'EOF'
reget /remote/path/large_file.zip
EOF
```

**备选 scp**（简单场景）：
```bash
scp local_file.txt <别名>:/remote/path/
scp -r local_dir/ <别名>:/remote/path/
scp <别名>:/remote/path/file.txt ./
```

**不需要任何脚本，所有操作通过SSH完成。**

### 🔴 三条必须遵守的远程执行规则

这三条都是实战踩出来的，违反后的失败模式都很隐蔽（不报错 / 静默失败 / 误判成功）。

#### 1. 非交互 ssh 一律加 `< /dev/null`

不加时 ssh 会继承当前 stdin 并等待输入，表现为命令卡死到超时。

```bash
ssh <别名> "命令" < /dev/null
```

#### 2. 禁止远程嵌套 heredoc —— 会静默失败

```bash
# ❌ 不写入、不报错、返回 0，最坑的一种失败
ssh <别名> 'cat >> /root/.ssh/config << "EOF"
Host xxx
EOF'
```

外层 ssh 引号与内层 heredoc 定界符互相干扰，命令被本地 shell 吃掉一部分。

```bash
# ✅ 短内容用 printf
ssh <别名> "printf 'line1\nline2\n' >> /path/file" < /dev/null

# ✅ 长内容本地写好再传（推荐）
cat > /tmp/x.conf << 'EOF'
...
EOF
scp /tmp/x.conf <别名>:/path/
```

**任何远程写文件操作，写完必须 grep / cat 回读确认。**

#### 3. 长任务后台跑 + 轮询日志

`npm ci && npm run build`、大型解压、镜像拉取等经常超过 2 分钟，直接 ssh 执行会撞工具超时。

```bash
ssh <别名> "cd /opt/<项目> && nohup bash -c '<长命令>' > /tmp/<项目>-build.log 2>&1 & echo started" < /dev/null

sleep 60
ssh <别名> "tail -25 /tmp/<项目>-build.log" < /dev/null
```

#### 补充：偶发 banner exchange 超时

`Connection timed out during banner exchange` 是网络抖动，不是配置问题。`sleep 15-20` 后重试即可，**不要因此去改 SSH 配置**。

---

## GitHub 私有仓库 → 服务器部署

当任务包含「建 GitHub 仓库 + 部署到服务器」时，走 Deploy Key 方案，
完整流程见 **`references/github-deploy-guide.md`**（含 nginx 配置、更新脚本、检查清单）。

### 核心链路

```bash
# 1. 本地建仓 + 私有仓库 + 推送
git init -q && git add -A && git commit -F - << 'EOF'
<提交信息>
EOF
git branch -M main
gh repo create <repo> --private --source=. --remote=origin
git push -u origin main
gh repo view <owner>/<repo> --json visibility    # 必须确认 PRIVATE

# 2. 本地生成 Deploy Key（不在服务器生成）
ssh-keygen -t ed25519 -f ~/.ssh/<repo>-deploy -N "" -C "deploy-key@<repo>-<服务器别名>"

# 3. 公钥加到仓库，只读（不加 --allow-write 即只读）
gh repo deploy-key add ~/.ssh/<repo>-deploy.pub --repo <owner>/<repo> --title "<服务器别名> (read-only)"

# 4. 私钥传服务器，权限 600
scp ~/.ssh/<repo>-deploy <别名>:/root/.ssh/<repo>-deploy
ssh <别名> "chmod 600 /root/.ssh/<repo>-deploy" < /dev/null

# 5. 服务器 SSH config 加 Host 别名（printf，不用 heredoc）
ssh <别名> "printf '\nHost github-<repo>\n    HostName github.com\n    User git\n    IdentityFile /root/.ssh/<repo>-deploy\n    IdentitiesOnly yes\n    StrictHostKeyChecking accept-new\n' >> /root/.ssh/config && grep -A 6 'Host github-<repo>' /root/.ssh/config" < /dev/null

# 6. 验证认证（先单独验，别直接 clone）
ssh <别名> "ssh -o BatchMode=yes -T github-<repo> 2>&1 | head -3" < /dev/null
# 期望：Hi <owner>/<repo>! You've successfully authenticated
# 仓库名不对 = IdentitiesOnly 没生效

# 7. clone（host 用别名，不是 github.com）
ssh <别名> "cd /opt && git clone git@github-<repo>:<owner>/<repo>.git <repo>" < /dev/null
```

### 三个关键点

| 点 | 原因 |
|---|---|
| **Deploy Key 设只读** | 服务器只需 pull。单仓库权限，泄露影响面远小于个人 token |
| **`IdentitiesOnly yes` 不能省** | 服务器上多个项目的 deploy key 会被 SSH 挨个试，GitHub 认第一个匹配的身份 → 报 `Repository not found`，且错误信息完全不提示真实原因 |
| **密钥本地生成** | 少一次往返；`-C` 注释带上仓库名+服务器名，是日后分辨密钥归属的唯一线索 |

### 部署避坑速查

| 坑 | 正确做法 |
|---|---|
| 只看 nginx 配置选端口 | 同时查 `grep -rh listen /etc/nginx/sites-available/` **和** `ss -tln`（实测有端口不在 nginx 配置里但已被占用） |
| 静态站抄 SPA 的 `try_files` | 静态导出用 `try_files $uri $uri/ $uri.html =404;` + `error_page 404 /404.html;`。SPA 回退会让所有错误 URL 返回首页 + 200，害 SEO |
| 静态站也跑 `next start` | `output: 'export'` 产物 nginx 直接托管即可，不需要常驻 Node 进程 |
| 部署脚本不校验产物 | 构建失败时旧 `out/` 还在，reload 后站点照常访问 → 误判成功。必须 `test -f out/index.html \|\| exit 1` |
| 只验证内网 | 内网 + 外网都要测，且**必须测一个不存在的路径**确认返回 404 |
| `git reset --hard` 后拉取冲突 | 该命令不删未跟踪文件。先手动传后来才纳入版本管理的文件要先 `rm -f` 再拉 |

---

## 命令参考

### sshctrl（初始配置用）

```bash
# 配置服务器免密连接（仅需执行一次）
python sshctrl.py server add <host> <用户名> <密码> [别名] [--port 端口]

# 自动修复服务端公钥认证（免密失败时）
python sshctrl.py server repair-pubkey <别名> <密码>

# 列出已配置服务器
python sshctrl.py server list

# 移除服务器配置
python sshctrl.py server remove <别名>

# SSH连接（可选，日常直接用 ssh <别名> 即可）
python sshctrl.py server ssh <别名> [命令]

# 为协作者创建受限账号（非 root、仅密码登录、按档位授权）
python sshctrl.py server add-collaborator <管理员别名> <用户名> <档位> [选项]
```

### 给协作者开受限账号，而不是共享 root

**场景**：有协作开发者需要登录服务器，但不想给对方 root 权限，也不想让对方走免密（希望对方就是拿一个账号密码登录，权限被限定在规定范围内）。

`server add-collaborator` 会：
1. 用管理员别名（已配置好免密）远程创建一个新的 Linux 账号，自动生成随机强密码（也可用 `--password` 自定义）
2. 按档位授权，不多给任何权限
3. 在 `/etc/ssh/sshd_config` 追加一个只针对这个新账号的 `Match User` 块：开启该账号的密码登录、**关闭该账号的免密登录**（`PubkeyAuthentication no`），root 和其他已有账号的策略完全不受影响
4. 备份配置、`sshd -t` 校验、reload、用 `sshd -T -C user=<账号>` 只读校验生效策略（不会用 sshpass 之类的方式去真的拿密码测试登录，遵守本技能"禁止密码自动化"的规则）

四档权限模板：

| 档位 | 说明 | 关键参数 |
|---|---|---|
| `readonly-deploy` | 只读+部署：能读写指定项目目录，无通用 sudo，可选授权重启指定服务 | `--group <已存在的项目属组>`、`--restart-service <服务名>`（可重复） |
| `full-shell` | 完整 shell，无 sudo：普通用户权限，不加入 sudo/wheel/docker 组 | 无 |
| `sudo-whitelist` | 特定命令 sudo 白名单：只能免密执行显式列出的绝对路径命令，其余一律拒绝 | `--sudo-cmd <绝对路径命令>`（必填，可重复） |
| `sftp-only` | 只 SFTP，不给 shell：chroot 到指定目录，只能上传/下载文件 | `--chroot-dir <绝对路径>`（必填） |

示例：

```bash
# 只读+部署：加入 deploy 组，并允许免密重启 myapp 服务
python sshctrl.py server add-collaborator myserver alice readonly-deploy \
  --group deploy --restart-service myapp

# 完整 shell，无 sudo
python sshctrl.py server add-collaborator myserver bob full-shell

# 特定命令 sudo 白名单：只能重启一个指定的 docker 容器
python sshctrl.py server add-collaborator myserver carol sudo-whitelist \
  --sudo-cmd "/usr/bin/docker restart myapp-container"

# 只 SFTP，chroot 到指定目录，无 shell
python sshctrl.py server add-collaborator myserver dave sftp-only \
  --chroot-dir /srv/sftp/dave
```

**注意事项**：
- `readonly-deploy` 依赖你已经把项目目录设成组可写（如 `chown -R :deploy /opt/app && chmod -R 2775 /opt/app`），本命令只负责把账号加入这个属组，不会替你改目录权限。
- `--group` 必须是已存在的属组，工具不会替你静默新建，避免误建出权限不明的组。
- 密码只在命令输出里显示一次，不落盘，请立即转发给协作者并妥善保管；对方连接方式是原生 `ssh <账号>@<服务器IP> -p <端口>`，不需要你的私钥或本地别名。
- 该账号无法免密登录（`PubkeyAuthentication no` 只对这一个账号生效），root 和其他既有账号的免密策略不受影响。
- 若账号已存在、或 `sshd_config` 里已有同名 `Match User` 块，命令会直接中止，不会覆盖已有配置。

### SSH（日常操作用）

```bash
# 连接并执行命令
ssh <别名> "命令"

# 文件上传
scp local_file.txt <别名>:/remote/path/

# 文件下载
scp <别名>:/remote/path/file.txt ./

# 目录同步
rsync -avz --progress local_dir/ <别名>:/remote/path/
```

---

## 故障排除

| 问题 | 解决 |
|------|------|
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | `ssh-keygen -R <服务器IP>` |
| 免密验证失败 | `ssh <别名> "whoami"` 检查 |
| 私钥权限错误 | `chmod 600 ~/.ssh/id_ed25519_*` |
| **密码认证失败（密码正确）** | **检查是否已配置该服务器（见下方）** |

```bash
# 诊断
ssh <别名> "sshd -T | grep -E 'pubkeyauth|authorizedkeys'"
ssh <别名> "ls -l ~/.ssh/authorized_keys"
```

### 特例1：密码正确但认证失败

**症状**：
- `sshctrl.py server add` 报错"认证失败"
- paramiko 密码连接失败
- 密码和用户名确认无误

**原因**：服务器已配置SSH密钥，系统优先使用密钥认证

**诊断步骤**：
```bash
# 1. 检查 known_hosts
ssh-keygen -F <服务器IP>

# 2. 检查密钥文件
ls -la ~/.ssh/ | grep <IP_格式化>

# 3. 检查 SSH config
cat ~/.ssh/config | grep -A 10 <IP>

# 4. 查找别名
cat ~/.ssh/config | grep -B 1 "HostName <IP>"
```

**解决方案**：
```bash
# 如果找到已存在的别名，直接使用
ssh <已存在的别名> "命令"

# 如果需要重新配置，先删除旧配置
python sshctrl.py server remove <旧别名>
# 然后重新添加
python sshctrl.py server add <host> <用户> <密码> [新别名]
```

**案例**：参考 `SSH别名冲突问题复盘-2026-05-23.md`

### 关键特例：脚本显示配置完成，但免密仍失败

当 `sshctrl.py server add` 输出“配置完成”但 `ssh <别名>` 仍失败时，按下面顺序排查：

```bash
# 1) 先排除 known_hosts 冲突
ssh-keygen -R <服务器IP>

# 2) 禁止交互模式，快速看真实认证结果
ssh -vvv -o BatchMode=yes -o ConnectTimeout=10 <别名> "echo ok"
```

如果日志末尾是 `Permission denied (password)`，说明公钥未被服务端接受。此时在服务器侧检查：

```bash
sshd -T | grep -E 'pubkeyauthentication|passwordauthentication|authorizedkeysfile'
```

若返回 `pubkeyauthentication no`，需要先开启公钥认证，再重载 `sshd`。否则该技能只能走密码路径，无法达到“免密 + 原生 ssh”成功标准。

---

## 文件结构

```
ssh-remote-control/
├── sshctrl.py           # 初始配置CLI（仅用于建立免密连接）
├── SKILL.md             # 本文档
├── README.md            # 用户文档
└── references/         # 参考资料
    ├── ssh-commands-reference.md  # SSH命令完整参考
    └── github-deploy-guide.md     # GitHub 私有仓库 + Deploy Key → 服务器部署完整流程
```

---

## 成功标准

1. `ssh <别名> "whoami"` 无需密码执行成功
2. 用户确认可以直接使用SSH命令操作服务器
3. 后续操作不需要任何脚本
4. （建议）`ssh -o BatchMode=yes <别名> "echo ok"` 返回成功
5. （建议）服务器 `sshd -T` 显示 `pubkeyauthentication yes`

---

## 自动化闭环（新增）

当 `server add` 后免密失败，统一按以下闭环执行：

1. `python sshctrl.py server repair-pubkey <别名> <密码>`
2. `ssh -o BatchMode=yes <别名> "whoami && hostname"`
3. `ssh <别名> "uptime && free -h && df -h /"`

这三步通过后，即可认为技能完成“可稳定复用”的交付标准。

### ⚠️ 重要陷阱：`repair-pubkey` 会静默关闭 root 密码登录

`repair-pubkey` 为了让 root 走通公钥认证，会把 `PermitRootLogin` 设为
`prohibit-password`（等同旧版 `without-password`）。这个值**只影响 root**，
且语义是"root 只能用密钥登录，密码登录直接拒绝"——即使
`PasswordAuthentication` 仍是 `yes`，root 用密码登录也会被拒绝
（`Permission denied (publickey,password)`）。

**如果用户要求"密码登录和免密登录都要能用"**：
1. 先确认是否真的需要 root 密码登录，优先建议新建一个 sudo 权限受限的
   部署用户走密码通道，而不是直接放开 root。
2. 若用户坚持要 root 双通道，需要手动把 `PermitRootLogin` 改成 `yes`
   （`repair-pubkey` 不会做这一步，因为这会扩大攻击面，必须显式确认）：
   ```bash
   ssh <别名> "cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.\$(date +%F-%H%M%S) && sed -i 's/^PermitRootLogin.*/PermitRootLogin yes/' /etc/ssh/sshd_config && sshd -t && systemctl reload sshd"
   ```
3. 改完之后明确提醒用户：root 密码登录已放开，存在被暴力破解的风险，
   建议加白名单 / fail2ban。
4. 验证密码通道时，遵守"禁止 sshpass"规则——不要在此技能里用密码自动化
   验证，改为让用户自行用密码交互登录一次确认，或只验证 `sshd -T` 的
   `permitrootlogin`/`passwordauthentication` 输出是否符合预期。

（复盘于 2026-08-12：`server add` 完成后免密验证一次因网络抖动超时崩溃，
`repair-pubkey` 修复后又把 root 密码登录静默关掉，用户要求两者都能用时才
发现。已同步修复：验证步骤加超时兜底，`repair-pubkey` 改 root 密码登录策略
时会打印警告。）

### 部署任务的额外验收标准

涉及 GitHub 仓库 + 服务器部署时，以下全部通过才算交付完成：

1. `gh repo view <owner>/<repo> --json visibility` 返回 `PRIVATE`
2. `gh repo deploy-key list` 显示为 **read-only**
3. `ssh <别名> "ssh -T github-<repo>"` 返回的**仓库名正确**
4. 内网 + 外网各路由均 200，且**不存在的路径返回 404**（验证 `try_files` 写对）
5. 更新脚本已纳入版本管理，并**端到端实跑过一次**（不能只当文档留着）

---

## 调用策略（防偏航）

当代理在其他项目调用本技能时，必须显式遵守：

1. **配置前必须先检查**：执行 `server add` 前，先检查 `~/.ssh/config` 是否已有该服务器配置
2. 必须使用 `$ssh-remote-control` 技能。
3. 必须使用原生命令：`ssh <别名> "..."` / `scp ...`。
4. 禁止 `python <<'PYEOF'`、`paramiko`、`sshpass` 等密码或脚本执行路径。
5. 若首次配置，最多只允许一次 `python sshctrl.py server add ...` 用于引导免密。
6. **非交互 ssh 一律加 `< /dev/null`**；**禁止远程嵌套 heredoc**（静默失败），改用 `printf` 或本地写好后 `scp`；**远程写文件后必须回读确认**。
7. 涉及「建 GitHub 仓库 + 部署服务器」时，走 Deploy Key（只读 + `IdentitiesOnly yes`），详见 `references/github-deploy-guide.md`。禁止在服务器上 `gh auth login` 或把 PAT 写进 remote URL。

推荐任务前置提示词：
```text
使用 $ssh-remote-control 技能。
禁止 python<<PYEOF、paramiko、sshpass。
只用 ssh/scp：ssh <alias> "<command>"。
```

若出现错误调用，立即中断并重定向：
```text
停止当前实现。你违反了远程执行策略。
重新执行：仅使用 `ssh <alias> "<command>"`。
```

---

## 设计理念

**保持简单**：
- 初始配置用一个小脚本
- 日常操作用原生SSH命令
- 不造轮子，不写冗余脚本
