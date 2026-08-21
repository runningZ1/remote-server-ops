# Cloudflare 域名绑定与子域名部署

> 适用场景：项目已经部署到服务器（nginx 静态站 / 反代端口），现在要挂一个真实域名，域名的 DNS 托管在 Cloudflare。
> 首次验证：2026-08-20，grade8.trumen.club → 198.44.177.126:8094（grade8-study-web）

---

## 决策门槛：这份文档 vs `ip-https-deployment.md`

| 场景 | 用哪份文档 |
| --- | --- |
| 用户有自己的域名，且域名 DNS 托管在 Cloudflare | 本文档 |
| 用户没有域名，只想让裸 IP 有可信 HTTPS | [ip-https-deployment.md](ip-https-deployment.md) |
| 用户有域名但**不**托管在 Cloudflare（阿里云 DNS / 腾讯云 DNS / 自建 DNS 等） | 流程思路相同，但第 2 步的 DNS 记录创建方式要换成对应服务商的 API/控制台，其余步骤（nginx + certbot）通用 |

两份文档不冲突：域名证书用 Let's Encrypt 标准 HTTP-01（走 `certbot --nginx`），不需要 `ip-https-deployment.md` 里那套 `--ip-address` IP 证书流程。

---

## 步骤 0：MCP 调用边界（强制）

Cloudflare 的 DNS 读写操作走的是 Cloudflare MCP 工具（`cloudflare-api` / `cloudflare-bindings` 插件），**不是**本技能的 `sshctrl.py`。按用户全局规则：

- 所有 MCP 工具调用必须通过 `mcp-executor` 子代理完成，不能在主对话里直接调用。
- 只读查询（列 zone、列 DNS 记录）和写操作（创建/修改/删除 DNS 记录）都走子代理，但写操作前必须先把"要创建什么记录"讲清楚给用户确认，不要让子代理静默创建。

---

## 步骤 1：发现 Zone（只读）

不要假设账号下只有一个 zone，也不要假设 zone_id。用子代理跑一次只读查询：

```text
请使用 Cloudflare MCP 工具列出当前账号下的所有域名（zones），返回每个 zone 的 name 和 zone_id，
并列出该 zone 现有的 DNS 记录（尤其是已有的子域名 A/CNAME 记录，用于判断命名风格和是否代理）。
只读查询，不做任何修改。
```

拿到结果后核对两件事：

1. 目标域名确实在这个账号下（不要假设用户只有一个域名）。
2. 观察已有子域名记录的 **命名风格**（比如 `ecom.trumen.club`）和 **proxied 状态**，新记录应该跟现有风格保持一致，除非用户明确要求不同配置。

---

## 步骤 2：确认子域名前缀（问用户，不要替用户决定）

必须向用户确认子域名前缀（例如 `grade8` / `study` / `app`），不要自己拍板命名。已有多个候选时用 `AskUserQuestion` 列出来，而不是直接选一个"看起来合理"的。

---

## 步骤 3：Proxied（橙色云朵）vs DNS-only（灰色云朵）

| 选 Proxied（推荐默认） | 选 DNS-only |
| --- | --- |
| 想要 Cloudflare 的 CDN 缓存、WAF、隐藏源站 IP、DDoS 防护 | 应用需要看到访问者真实 IP 且没有正确处理 `CF-Connecting-IP` 头 |
| 源站证书出问题时还能兜底（Cloudflare 边缘证书） | 需要非 80/443 端口直接对外（Cloudflare 代理只转发 80/443/8080/8443 等白名单端口） |
| 与同 zone 下其他记录风格一致 | 做证书调试、ACME 排障，想跳过 Cloudflare 这一层看真实源站响应 |

默认跟随同 zone 下其他记录（大多数账号会统一开 Proxied）。如果无法判断，问用户，不要自己默默选一个。

**开了 Proxied 之后的连锁影响，必须提前告知用户：**

- ACME HTTP-01 验证请求会经过 Cloudflare 边缘再到源站，一般能正常工作，但如果账号开了 "I'm Under Attack" 模式或严格的 WAF 规则，可能拦截 certbot 的验证请求，需要临时降级安全等级。
- SSL/TLS 加密模式要匹配：源站有真实 Let's Encrypt 证书时，Cloudflare 的 SSL/TLS 模式应设为 **Full (strict)**；如果源站只有自签名证书，Full (strict) 会导致 502。这个设置在 Cloudflare 控制台里，MCP 工具通常也能查（`zones/{id}/settings/ssl`），但目前多数账号是手工配置好的，先假设已经是 Full (strict)，出问题再检查。

---

## 步骤 4：创建 DNS 记录（写操作，需要用户确认后再执行）

```text
请使用 Cloudflare API 在 zone_id=<zone_id> 下创建一条 DNS 记录：
- 类型: A
- 名称: <前缀>.<域名>
- 内容: <服务器公网 IP>
- proxied: <true/false，按步骤 3 的结论>
- TTL: 自动（1）
创建后请再次查询确认记录已生效，并汇报 record id、name、type、content、proxied 状态。
```

创建后建议顺手更新本地的"已部署站点记录"表（每个项目仓库里常见的 `部署记录.md` 之类文件），补上域名和 zone_id 两列，方便下次直接查表而不用再问一遍 Cloudflare：

```markdown
| 本地文件夹 | 网站名称 | 域名 | Cloudflare Zone | 服务器路径 |
|---|---|---|---|---|
| xxx | xxx | grade8.trumen.club | trumen.club (zone_id: xxx) | /opt/grade8-study-web |
```

---

## 步骤 5：nginx 配置 + certbot 签发证书

### 5.1 新建 80 端口 server block

参考已有站点风格（不要凭空发明格式），本地写好再 `scp` 上传，避免远程 heredoc 的坑（见 `github-deploy-guide.md` 踩坑记录 1）：

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name <前缀>.<域名>;

    root /opt/<项目目录>;
    index index.html;

    gzip on;
    gzip_vary on;
    gzip_comp_level 6;
    gzip_min_length 256;
    gzip_types text/plain text/css text/xml application/json application/javascript application/xml image/svg+xml;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

```bash
scp <本地配置文件> <别名>:/etc/nginx/sites-available/<站点名>
ssh <别名> "ln -sf /etc/nginx/sites-available/<站点名> /etc/nginx/sites-enabled/<站点名> && nginx -t && systemctl reload nginx" < /dev/null
```

若应用是反代到内部端口而不是静态文件，参照 `ip-https-deployment.md` 里的 `proxy_pass` 写法替换 `root`/`location /`。

### 5.2 签发证书：`--cert-name` 是关键，不能省

```bash
ssh <别名> "certbot --nginx -d <前缀>.<域名> --cert-name <前缀>.<域名> --non-interactive --agree-tos -m <邮箱> --redirect" < /dev/null
```

**为什么必须显式传 `--cert-name`：** 如果服务器上已经存在其他证书（例如某个裸 IP 证书、通配符证书，或历史遗留证书），且 certbot 判断新请求与旧证书存在关联但密钥类型不同（ECDSA vs RSA），会直接报错拒绝执行：

```text
Are you trying to change the key type of the certificate named ip-198-44-177-126-staging from ECDSA to RSA?
Please provide both --cert-name and --key-type on the command line to confirm the change you are trying to make.
```

不显式传 `--cert-name`，certbot 会尝试复用/推断一个已有证书槽位，容易踩到这个坑。**永远显式指定 `--cert-name <完整域名>`**，让 certbot 用域名本身作为证书标识，与其他证书互不干扰。

签发成功后 certbot 会自动：
- 在 443 server block 里写入 `ssl_certificate` / `ssl_certificate_key`。
- 加一个 80→443 的 301 跳转 server block（因为传了 `--redirect`）。
- 注册自动续期任务（systemd timer 或 cron，视发行版而定）。

---

## 步骤 6：验证（关键：不要被 Cloudflare 挑战页骗了）

### 6.1 源站直连验证（绕过 Cloudflare，确认 nginx/证书本身没问题）

```bash
ssh <别名> "curl -sk -o /dev/null -w 'HTTP %{http_code}\n' -H 'Host: <前缀>.<域名>' https://127.0.0.1:443/" < /dev/null
```

这一步应该直接拿到 `200`。如果这里就失败，问题在源站（nginx 配置 / 证书路径），跟 Cloudflare 无关，不用往下查。

### 6.2 公网验证：`curl` 拿到 403 是正常现象，不是部署失败

用裸 `curl`（无自定义 UA）通过公网域名访问，经常会拿到 Cloudflare 的 **Managed Challenge**（"Just a moment..." 页面，HTTP 403），尤其是：

- 请求来自服务器自己的出口 IP（自己 curl 自己的域名，容易被判定为可疑流量）；
- zone 开启了 Bot Fight Mode / 较高的 Security Level；
- 请求没有浏览器特征（User-Agent、Accept 头等）。

**这不代表部署失败。** 正确的验证方式：

```bash
curl -s -o /dev/null -w 'HTTP %{http_code}\n' \
  -A "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36" \
  https://<前缀>.<域名>/
```

带上浏览器 UA 之后应该拿到 `200`。如果同 zone 下其他已知正常的域名（比如老站点）用裸 `curl` 也返回 403，就更能确认是 zone 级别的机器人防护，不是新记录本身的问题——把这一步作为交叉验证，而不是干等或反复重试同一个请求。

真正的失败信号是：换了浏览器 UA 依然非 200，或者响应体不是 Cloudflare 的挑战页而是别的错误（502/522 等，代表 Cloudflare 连不上源站）。

---

## 踩坑记录

### 坑 1：certbot 报 "change the key type" 错误

见步骤 5.2。根因是没有显式传 `--cert-name`，certbot 自己去猜关联证书猜错了。**永远显式传 `--cert-name <域名>`。**

### 坑 2：拿裸 `curl` 测试域名，看到 403 就误判部署失败

见步骤 6.2。先查是不是 Cloudflare 挑战页（响应体里能看到 `Just a moment` / `cf_chl_opt` 字样），不是 nginx/证书问题就不要往那个方向排查。

### 坑 3：不看已有记录风格，独立决定 proxied 状态

新记录跟同 zone 下其他记录风格不一致（比如别的都是 proxied，新的是 DNS-only），容易造成用户困惑（"为什么这个子域名没有 CDN 加速/WAF 防护"）。创建前先看一眼同 zone 现有记录。

---

## 检查清单

- [ ] 已用只读查询确认目标域名在 Cloudflare 账号下，拿到正确的 zone_id
- [ ] 子域名前缀已经问过用户确认，不是自己拍板
- [ ] Proxied 状态跟同 zone 现有记录风格一致，或已经跟用户确认例外
- [ ] DNS 记录创建前，已经把要创建的具体内容讲给用户看过
- [ ] DNS 记录创建后，二次查询确认已生效
- [ ] nginx 80 端口 server block 已上传，`nginx -t` 通过后才 reload
- [ ] certbot 签发时显式传了 `--cert-name <完整域名>`
- [ ] 源站直连（`curl -H Host: ...127.0.0.1`）验证通过
- [ ] 公网验证用了浏览器 UA，不是仅凭裸 `curl` 403 就下结论
- [ ] 本地"已部署站点记录"表已经补上域名和 zone_id
