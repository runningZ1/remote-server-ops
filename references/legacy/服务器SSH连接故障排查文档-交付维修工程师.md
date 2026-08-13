# 服务器 SSH 连接故障排查文档（交付维修工程师）

## 1. 基本信息
- 文档生成时间：2026-04-30（Asia/Shanghai）
- 目标服务器 IP：`38.76.206.12`
- 登录用户：`root`
- 期望目标：通过 SSH 成功连接服务器，并进一步检查服务器运行状态（CPU/内存/磁盘/负载/进程）
- 本地执行环境：Windows PowerShell（OpenSSH_for_Windows_9.5p2）
- 使用技能目录：`C:\Users\zijie\.agents\skills\ssh-remote-control`

## 2. 用户诉求与沟通摘要
用户提供了服务器信息（IP、root、密码）并要求：
1. 按 `ssh-remote-control` 技能流程连接服务器。
2. 查看服务器运行状态。

在排查过程中，用户配合执行了云防火墙（安全组）策略调整，并询问策略填写方式。建议用户将策略收紧为仅放行 SSH 所需端口和来源 IP，随后用户反馈策略已更新成功，并要求继续尝试连接。

## 3. 现场现象（核心故障）
虽然 TCP 22 端口可达，但 SSH 协议握手阶段超时，远端未返回 SSH banner，导致无法完成认证前流程。

典型报错：
- `Connection timed out during banner exchange`
- `Error reading SSH protocol banner`
- `READ_TIMEOUT`（直接读取 TCP 22 banner 超时）

这意味着：
- 网络层到 22 端口存在连通性；
- 但应用层 SSH 服务（`sshd`）未按预期返回协议头，或被中间链路/策略设备吞掉。

## 4. 已执行步骤与命令记录

### 4.1 按技能文档读取与执行
已读取：`SKILL.md`、`README.md`、`sshctrl.py`。

技能规定流程：
1. 一次性配置免密：`sshctrl.py server add <IP> <user> <password> [alias]`
2. 日常操作：`ssh <alias> "命令"`

实际执行：
```powershell
py sshctrl.py server add 38.76.206.12 root <password> cmserver
```
结果：失败于第 1 步“测试 SSH 连接”，报错：
- `No existing session`
- `Error reading SSH protocol banner[WinError 10038]`

### 4.2 端口连通性检查
命令：
```powershell
Test-NetConnection 38.76.206.12 -Port 22
```
结果：
- `TcpTestSucceeded : True`

结论：目标 22 端口在 TCP 层可达。

### 4.3 原生 SSH 直接连接与调试
命令：
```powershell
ssh -o ConnectTimeout=10 root@38.76.206.12 "whoami && hostname && uptime"
ssh -vvv -o ConnectTimeout=10 -o ConnectionAttempts=1 root@38.76.206.12 "exit"
```
结果：
- 连接建立（TCP connect success），但卡在协议交换：
  - `Local version string SSH-2.0-OpenSSH_for_Windows_9.5`
  - `Connection timed out during banner exchange`

结论：未进入认证阶段，问题发生在 SSH banner 交换。

### 4.4 直接读取 22 端口 banner
命令（PowerShell TCPClient 读取首包）：
```powershell
$client = New-Object System.Net.Sockets.TcpClient
... connect 38.76.206.12:22 ...
... read stream ...
```
结果：
- `READ_TIMEOUT`

结论：远端未在超时时间内回送 SSH banner（例如 `SSH-2.0-...`）。

## 5. 用户侧策略调整（沟通中已完成）
用户提供了“编辑策略”页面截图并咨询参数。

给出的建议：新增 SSH 放行策略（入方向、TCP、端口 22、来源为当前公网 IP/32）。
同时指出：
- `0.0.0.0/0 + 1-65535` 过宽，存在安全风险。

用户反馈：防火墙策略已更新成功。

更新后再次全量重试（`sshctrl.py` + `ssh -vvv` + banner 读取）结果**无变化**，仍为 banner 超时。

## 6. 当前结论（供维修工程师判断）
问题不在客户端命令使用方式，已覆盖脚本与原生 SSH 两种路径。

高概率故障点在服务器侧或中间网络设备，典型包括：
1. 服务器 `sshd` 未正常运行/卡死。
2. `sshd` 未监听预期地址或端口（非 22 或仅内网监听）。
3. 主机防火墙（iptables/firewalld/ufw）拦截或异常丢包。
4. 云侧仍存在未生效或叠加的 ACL/NACL/安全设备策略。
5. 22 端口被转发到非 SSH 服务，导致无 banner 返回。

## 7. 建议维修工程师在服务器控制台执行的检查
请在服务器本机控制台（VNC/串口）执行并回传结果：

```bash
systemctl status sshd --no-pager -l
journalctl -u sshd -n 100 --no-pager
ss -lntp | grep ':22'
cat /etc/ssh/sshd_config | grep -E '^(Port|ListenAddress|PermitRootLogin|PasswordAuthentication|PubkeyAuthentication)'
iptables -S
```

可追加：
```bash
# 若使用 firewalld
firewall-cmd --list-all

# 若使用 ufw
ufw status verbose

# 验证 sshd 配置合法性
sshd -t
```

## 8. 修复后验收标准
修复完成后应满足：
1. 客户端执行 `ssh root@38.76.206.12 "whoami && hostname"` 可成功返回。
2. `sshctrl.py server add 38.76.206.12 root <password> cmserver` 可完成免密配置。
3. `ssh cmserver "uptime && free -h && df -h"` 可稳定输出。

## 9. 后续操作计划（连接恢复后）
一旦 SSH 恢复可用，将立即执行以下运行状态采集：
```bash
uptime
free -h
df -h
top -bn1 | head -n 20
ps -eo pid,ppid,cmd,%mem,%cpu --sort=-%cpu | head
systemctl --failed
docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'  # 若有 Docker
```
并整理成运行状态报告反馈给用户。

---
如需我继续跟进，请在服务器侧修复后通知，我将直接完成免密配置与状态巡检。
