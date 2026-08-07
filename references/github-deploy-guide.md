# GitHub 私有仓库 → 服务器部署完整流程

> 适用场景：本地项目 → 创建私有 GitHub 仓库 → 服务器用 Deploy Key 拉取 → 部署
> 首次验证：2026-08-07，ai-cases-hub 项目部署到 198.44.177.126:8097

---

## 为什么用 Deploy Key 而不是别的

| 方案 | 问题 |
|---|---|
| 服务器上 `gh auth login` | 要在服务器存个人 token，权限覆盖你**所有**仓库 |
| HTTPS + PAT 写进 remote URL | token 明文存在 `.git/config`，泄露面大 |
| 复用服务器已有的 id_ed25519 | 该密钥通常绑定个人账号，同样是全量权限 |
| **Deploy Key（推荐）** | 单仓库、可设只读、可单独吊销，泄露影响面最小 |

**Deploy Key 一律设只读**——服务器只需要 `git pull`，不需要写权限。

---

## 完整流程

### 前置检查

```bash
# 1. 服务器是否已配置免密（必查，见 SKILL.md）
cat ~/.ssh/config | grep -B 1 "HostName <IP>"

# 2. gh CLI 是否已登录，且有 repo scope
gh auth status
# Token scopes 里必须包含 'repo'，否则无法创建私有仓库
```

### 步骤 1：本地建仓并提交

```bash
cd <项目目录>
# .gitignore 先写好，别把 node_modules 提上去
git init -q
git add -A
git status --short | wc -l     # 确认文件数合理，没混进依赖目录
git commit -F - << 'EOF'
<提交信息>
EOF
git branch -M main
```

### 步骤 2：创建私有仓库并推送

```bash
gh repo create <repo-name> --private --source=. --remote=origin --description "<描述>"
git push -u origin main

# 必须验证 visibility 真的是 PRIVATE
gh repo view <owner>/<repo> --json name,visibility,url,defaultBranchRef
```

### 步骤 3：本地生成 Deploy Key

密钥在**本地**生成，只把私钥传上去。不要在服务器上生成再复制公钥回来（多一次往返，且容易忘记设权限）。

```bash
cd ~/.ssh
ssh-keygen -t ed25519 -f <repo>-deploy -N "" -C "deploy-key@<repo>-<服务器别名>"
cat <repo>-deploy.pub
```

`-C` 注释里带上仓库名和服务器名。服务器上密钥多了以后，这是唯一能分清谁是谁的线索。

### 步骤 4：公钥加到仓库（只读）

```bash
gh repo deploy-key add ~/.ssh/<repo>-deploy.pub \
  --repo <owner>/<repo> \
  --title "<服务器别名> (/opt deploy, read-only)"

# 确认存在且是 read-only
gh repo deploy-key list --repo <owner>/<repo>
```

不加 `--allow-write` 就是只读，这是默认行为。

### 步骤 5：私钥传到服务器

```bash
scp ~/.ssh/<repo>-deploy <服务器别名>:/root/.ssh/<repo>-deploy
ssh <服务器别名> "chmod 600 /root/.ssh/<repo>-deploy && ls -l /root/.ssh/<repo>-deploy" < /dev/null
```

权限必须是 600，否则 SSH 直接拒绝使用该密钥。

### 步骤 6：服务器配置 Host 别名

**用 printf 追加，不要用嵌套 heredoc**（原因见下方踩坑记录）：

```bash
ssh <服务器别名> "printf '\nHost github-<repo>\n    HostName github.com\n    User git\n    IdentityFile /root/.ssh/<repo>-deploy\n    IdentitiesOnly yes\n    StrictHostKeyChecking accept-new\n' >> /root/.ssh/config && chmod 600 /root/.ssh/config && grep -A 6 'Host github-<repo>' /root/.ssh/config" < /dev/null
```

**写完必须 grep 回读确认**，追加操作静默失败过。

#### `IdentitiesOnly yes` 是关键，不能省

一台服务器上跑多个项目时，`~/.ssh/` 下会堆着好几个 deploy key。SSH 默认会把目录里所有密钥挨个试给 GitHub，GitHub 认第一个匹配上的身份——于是你以为在拉 A 仓库，实际用的是 B 仓库的 key，报 `Repository not found`，且错误信息完全不提示真实原因，极难排查。

`IdentitiesOnly yes` 强制只用 `IdentityFile` 指定的那一把。

### 步骤 7：验证认证并克隆

```bash
# 先单独验证认证，不要直接 clone
ssh <服务器别名> "ssh -o BatchMode=yes -T github-<repo> 2>&1 | head -3" < /dev/null
# 期望输出：Hi <owner>/<repo>! You've successfully authenticated, ...
# 注意看仓库名对不对——名字不对就说明 IdentitiesOnly 没生效
```

```bash
ssh <服务器别名> "cd /opt && git clone git@github-<repo>:<owner>/<repo>.git <repo> && cd <repo> && git log --oneline -1" < /dev/null
```

clone URL 里的 host 用**别名** `github-<repo>`，不是 `github.com`。这是整个方案生效的关键。

---

## 步骤 8：部署（以静态站为例）

### 构建：长任务必须后台跑

`npm ci && npm run build` 经常超过 2 分钟，直接 ssh 执行会撞工具超时。

```bash
ssh <服务器别名> "cd /opt/<repo>/web && nohup bash -c 'npm ci --no-audit --no-fund && npm run build' > /tmp/<repo>-build.log 2>&1 & echo started" < /dev/null

# 轮询日志
sleep 60
ssh <服务器别名> "tail -25 /tmp/<repo>-build.log" < /dev/null
```

### 端口选择：必须双重检查

**只看 nginx 配置会选到已占用的端口。** 实测教训：8095 在所有 nginx 配置里都没出现，但系统上已有进程监听（其他方式启动的服务）。

```bash
# 两个都要查
ssh <别名> "grep -rh listen /etc/nginx/sites-available/ | tr -d '\t ' | sort -u"
ssh <别名> "ss -tln | grep -E ':(8096|8097)\b' || echo BOTH_FREE"
```

### nginx 配置：新增独立 server block，不动存量

先看一个现有站点配置当模板，匹配既有风格：

```bash
ssh <别名> "cat /etc/nginx/sites-available/<某个现有站点>"
```

本地写好配置再 scp 上传（比远程 heredoc 可靠）：

```bash
cat > /tmp/<repo>.conf << 'EOF'
server {
    listen 8097;
    listen [::]:8097;
    server_name _;

    root /opt/<repo>/web/out;
    index index.html;

    gzip on;
    gzip_vary on;
    gzip_comp_level 6;
    gzip_min_length 256;
    gzip_types text/plain text/css text/xml application/json application/javascript application/xml image/svg+xml;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # 构建产物带内容哈希，可长期缓存
    location /_next/static/ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    location / {
        try_files $uri $uri/ $uri.html =404;
    }

    error_page 404 /404.html;
}
EOF

scp /tmp/<repo>.conf <别名>:/etc/nginx/sites-available/<repo>
ssh <别名> "ln -sfn /etc/nginx/sites-available/<repo> /etc/nginx/sites-enabled/<repo> && nginx -t" < /dev/null
ssh <别名> "systemctl reload nginx" < /dev/null
```

#### `try_files` 不要无脑抄 SPA 写法

```nginx
# ❌ SPA 写法，用在静态导出站上是错的
try_files $uri $uri/ /index.html;

# ✅ 静态导出（Next.js export / Astro / Hugo 等）
try_files $uri $uri/ $uri.html =404;
error_page 404 /404.html;
```

SPA 回退会让**所有**错误 URL 都返回首页内容 + 200 状态码。对 SEO 有害（搜索引擎认为站内有大量重复页），也让线上问题难以发现。

#### 静态站不需要常驻 Node 进程

Next.js `output: 'export'` 产出纯静态文件，nginx 直接托管 `out/` 即可。比跑 `next start` 省内存、少一个要守护的进程。只有用到 SSR / API Routes / ISR 时才需要 PM2 守护 Node。

### 验证：内网 + 外网都要测

```bash
# 服务器内部
ssh <别名> "for p in / /about/ /nonexistent/; do printf '%-20s %s\n' \"\$p\" \"\$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8097\$p)\"; done" < /dev/null

# 外网（验证防火墙/安全组放行）
curl -s -o /dev/null -m 20 -w '%{http_code}\n' http://<IP>:8097/
```

必须包含一个**不存在的路径**，确认返回 404 而不是 200——这是检验 `try_files` 写对没有的唯一方法。

---

## 步骤 9：留一个更新脚本

纳入版本管理，放仓库根目录。

```bash
#!/usr/bin/env bash
# 用法：ssh <别名> "/opt/<repo>/deploy.sh"
set -euo pipefail

REPO=/opt/<repo>
cd "$REPO"

echo "==> 拉取最新代码"
git fetch --prune origin
git reset --hard origin/main

echo "==> 安装依赖"
cd "$REPO/web"
npm ci --no-audit --no-fund

echo "==> 构建"
npm run build

# 构建失败时 out/ 会残留旧产物，不检查就会把「构建挂了但旧页面还在」误报成部署成功
test -f "$REPO/web/out/index.html" || { echo "构建产物缺失，中止"; exit 1; }

echo "==> reload nginx"
nginx -t && systemctl reload nginx

echo "==> 验证"
for p in / /about/; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:8097$p")
  printf '  %-12s %s\n' "$p" "$code"
  [ "$code" = "200" ] || { echo "路由 $p 异常"; exit 1; }
done

echo "==> 部署完成"
```

三个要点：
- `set -euo pipefail`——任何一步失败立即停，不要带着半截状态继续
- **产物存在性检查**——`npm run build` 失败时旧的 `out/` 还在，reload 后站点照常访问，会误判成功
- **逐路由验证并在失败时 exit 1**——脚本要能被 CI 或人一眼看出成败

首次上传后端到端实跑一次，别只当文档留着。

---

## 踩坑记录

### 坑 1：远程嵌套 heredoc 静默失败

```bash
# ❌ 不写入，且不报错——最坑的一种失败
ssh <别名> 'cat >> /root/.ssh/config << "EOF"
Host xxx
EOF'
```

外层 ssh 的引号和内层 heredoc 的定界符互相干扰，命令被本地 shell 吃掉一部分。**不报错，返回 0，文件没变**。

```bash
# ✅ 方案 A：printf（短内容）
ssh <别名> "printf 'line1\nline2\n' >> /path/file" < /dev/null

# ✅ 方案 B：本地写好 + scp（长内容，推荐）
cat > /tmp/x.conf << 'EOF'
...
EOF
scp /tmp/x.conf <别名>:/path/
```

**任何远程写文件操作，写完都要 grep / cat 回读确认。**

### 坑 2：ssh 命令挂起被移到后台

不加 `< /dev/null` 时，ssh 会继承当前 stdin 并等待输入，表现为命令卡住直到超时。

```bash
# ✅ 所有非交互的 ssh 调用都加上
ssh <别名> "命令" < /dev/null
```

### 坑 3：偶发 `Connection timed out during banner exchange`

网络抖动导致，不是配置问题。`sleep 15-20` 后重试即可，不要因此去改 SSH 配置。

### 坑 4：`git reset --hard` 不会删未跟踪文件

先手动传到服务器、后来才纳入版本管理的文件（如 `deploy.sh`），在 `git reset --hard origin/main` 时因为是未跟踪状态不会被覆盖，之后 pull 会报冲突。把它先删掉再拉：

```bash
ssh <别名> "cd /opt/<repo> && rm -f deploy.sh && git fetch --prune origin && git reset --hard origin/main" < /dev/null
```

---

## 检查清单

- [ ] 服务器免密已配置（`ssh <别名> "whoami"` 免密通过）
- [ ] `gh auth status` 含 `repo` scope
- [ ] `.gitignore` 已排除依赖目录，`git status --short | wc -l` 文件数合理
- [ ] `gh repo view --json visibility` 确认是 `PRIVATE`
- [ ] Deploy Key 是 **read-only**
- [ ] 私钥权限 600
- [ ] 服务器 SSH config 含 **`IdentitiesOnly yes`**，且已 grep 回读确认
- [ ] `ssh -T github-<repo>` 返回的仓库名**正确**
- [ ] 端口同时查过 nginx 配置和 `ss -tln`
- [ ] `nginx -t` 通过后才 reload
- [ ] 内网 + 外网都验证过，且测过不存在路径返回 404
- [ ] 更新脚本已纳入版本管理并端到端实跑过
