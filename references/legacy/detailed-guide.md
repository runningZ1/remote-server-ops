# SSH远控 - 详细技术指南

本参考提供了设置SSH远程访问时的故障排除、边缘情况和平台特定注意事项的全面技术文档。

## 架构概述

SSH远控设置遵循7步工作流程：

1. **依赖安装** - 安装paramiko以进行非交互式SSH
2. **连接测试** - 验证凭证、启用公钥认证并安装tmux
3. **密钥生成** - 创建无密码Ed25519密钥对
4. **密钥上传** - 通过SFTP传输公钥
5. **权限修复** - 设置正确的文件权限（平台特定）
6. **别名配置** - 添加带有保活设置的SSH配置条目
7. **连接稳定性** - 使用tmux处理长时间运行的任务

## 技术深入

### 为什么使用Paramiko？

Claude Code的Bash工具在没有TTY（终端）的情况下运行，使得交互式密码提示不可能。传统工具会失败：

- 带密码的`ssh`：需要交互式输入
- `sshpass`：在Windows上的Git Bash中不可用
- Expect脚本：需要TTY

Paramiko是一个纯Python SSH实现，以编程方式处理认证，使其成为Claude Code中非交互式基于密码的SSH的唯一可靠解决方案。

### 为什么生成新密钥？

现有的SSH密钥（例如`~/.ssh/id_ed25519`）通常有密码短语保护。当SSH尝试使用受密码短语保护的密钥时，它会交互式提示输入密码短语。由于Claude Code无法提供交互式输入，认证会失败。

生成一个新的、专用于远程服务器的无密码密钥可以完全避免此问题。

### 为什么使用SFTP上传密钥？

使用`echo`或`cat`等shell命令写入公钥可能引入问题：

- **Shell转义**：密钥中的特殊字符可能被误解
- **BOM标记**：某些shell添加的字节顺序标记会破坏密钥
- **换行符问题**：Windows CRLF vs Unix LF

SFTP直接在二进制级别写入文件，避免所有shell解释问题。

### 为什么在Windows上使用icacls？

Git Bash在Windows上的`chmod`命令只更改Git元数据中存储的Unix风格权限位——它不影响实际的Windows文件权限。Windows上的OpenSSH检查NTFS权限，而不是Git元数据。

`icacls`是Windows原生工具，可修改OpenSSH信任的NTFS ACL（访问控制列表）。

## 平台特定说明

### Windows（Git Bash）

- 使用`python`命令（不是`python3`）
- 必须通过`icacls`设置私钥权限
- SSH配置路径：`C:\Users\<用户名>\.ssh\config`
- 配置中的密钥路径格式：使用正斜杠或`~/.ssh/keyname`

### Linux

- 使用`python3`命令（如果设置了别名则用`python`）
- 通过`chmod 600`设置私钥权限
- SSH配置路径：`/home/<用户名>/.ssh/config`
- 确保`~/.ssh`目录有700权限

### macOS

- 使用`python3`命令
- 通过`chmod 600`设置私钥权限
- SSH配置路径：`/Users/<用户名>/.ssh/config`
- 可能需要Xcode Command Line Tools来运行`ssh-keygen`

## 常见错误场景

### 错误：`Permission denied (publickey)`

**可能原因：**

1. **私钥权限太开放**
   - Windows：重新运行`icacls`修复
   - Linux/Mac：运行`chmod 600 ~/.ssh/id_ed25519_*`

2. **公钥不在authorized_keys中**
   - 验证：`ssh <别名> "cat ~/.ssh/authorized_keys"`
   - 如果缺失则重新上传

3. **PubkeyAuthentication已禁用**
   - 检查：`ssh <别名> "sshd -T | grep pubkeyauth"`
   - 应显示`pubkeyauthentication yes`

4. **使用的密钥错误**
   - 验证SSH配置有`IdentitiesOnly yes`
   - 检查`IdentityFile`路径正确

### 错误：`REMOTE HOST IDENTIFICATION HAS CHANGED`

**原因：**服务器的host key已更改（服务器重装或IP重用后常见）

**解决方案：**
```bash
ssh-keygen -R <服务器IP>
```

这会从`~/.ssh/known_hosts`中删除旧的host key。

### 错误：`Connection refused`或`Connection timed out`

**可能原因：**

1. **防火墙阻止SSH端口**
   - 验证端口22开放：`telnet <服务器IP> 22`
   - 检查服务器防火墙：`ssh <别名> "ufw status"`

2. **SSH服务未运行**
   - 检查：`ssh <别名> "systemctl status sshd"`
   - 启动：`ssh <别名> "systemctl start sshd"`

3. **IP地址错误**
   - 验证IP：`ping <服务器IP>`

### 错误：`Too many authentication failures`

**原因：**SSH在正确的密钥之前尝试了多个密钥，达到了服务器的`MaxAuthTries`限制

**解决方案：**确保SSH配置中有`IdentitiesOnly yes`以防止SSH尝试所有可用密钥

### 错误：`Load key "...": invalid format`

**原因：**私钥文件损坏或格式错误

**解决方案：**使用generate_ssh_key.py脚本重新生成密钥对

## 高级配置

### 使用非标准SSH端口

如果服务器使用端口22以外的端口，请修改SSH配置：

```
Host myserver
    HostName 192.168.1.100
    Port 2222
    User root
    IdentityFile ~/.ssh/id_ed25519_192_168_1_100
    IdentitiesOnly yes
```

### 同一服务器的多个密钥

为同一服务器上的不同用途使用不同密钥：

```
Host server-admin
    HostName 192.168.1.100
    User root
    IdentityFile ~/.ssh/id_ed25519_admin

Host server-deploy
    HostName 192.168.1.100
    User deploy
    IdentityFile ~/.ssh/id_ed25519_deploy
```

### 跳板主机（堡垒机）

通过跳板主机连接：

```
Host jumphost
    HostName bastion.example.com
    User jumpuser
    IdentityFile ~/.ssh/id_ed25519_jump

Host targetserver
    HostName 10.0.1.50
    User root
    ProxyJump jumphost
    IdentityFile ~/.ssh/id_ed25519_target
```

## 安全注意事项

### 无密码密钥

无密码密钥对方便自动化很方便，但如果本地机器被入侵则存在安全风险。请考虑：

- 为生产服务器使用受密码短语保护的密钥（需要手动解锁）
- 使用`authorized_keys`选项限制密钥使用（例如`from="192.168.1.0/24"`）
- 定期轮换密钥
- 对于大型部署使用SSH证书而不是密钥

### authorized_keys限制

在`authorized_keys`中的公钥添加限制：

```
command="/usr/local/bin/restricted-shell",no-port-forwarding,no-X11-forwarding,no-agent-forwarding ssh-ed25519 AAAAC3... claude-code
```

这限制了密钥即使被入侵也能做什么。

### 审计日志

在服务器上启用SSH日志以跟踪密钥使用：

```bash
# /etc/ssh/sshd_config
LogLevel VERBOSE
```

检查日志：`journalctl -u sshd -f`

## 故障排除检查清单

当SSH密钥认证失败时，按此顺序检查：

- [ ] 私钥权限（Linux/Mac上为0600，Windows上为限制性ACL）
- [ ] 公钥存在于服务器上的`~/.ssh/authorized_keys`中
- [ ] `authorized_keys`文件权限（0600）
- [ ] `~/.ssh`目录权限（0700）
- [ ] `/etc/ssh/sshd_config`中的`PubkeyAuthentication yes`
- [ ] SSH配置中的`IdentityFile`路径正确
- [ ] SSH配置中的`IdentitiesOnly yes`
- [ ] 主机名或用户名没有拼写错误
- [ ] 服务器的SSH服务正在运行
- [ ] 防火墙允许端口22（或自定义SSH端口）
- [ ] 没有冲突的SSH配置条目（首匹配优先）

## 性能优化

### 连接复用

要加快重复SSH连接，请在SSH配置中启用复用：

```
Host *
    ControlMaster auto
    ControlPath ~/.ssh/sockets/%r@%h-%p
    ControlPersist 600
```

创建套接字目录：
```bash
mkdir -p ~/.ssh/sockets
```

这会重用现有连接，使后续SSH命令几乎瞬时完成。

### 压缩

对于慢速网络，启用压缩：

```
Host slowserver
    HostName remote.example.com
    Compression yes
```

## 兼容性矩阵

| 本地OS | Python命令 | 权限工具 | SSH配置路径 |
|----------|---------------|-----------------|-----------------|
| Windows 10/11 | `python` | `icacls` | `C:\Users\<用户>\.ssh\config` |
| Ubuntu/Debian | `python3` | `chmod` | `/home/<用户>/.ssh/config` |
| CentOS/RHEL | `python3` | `chmod` | `/home/<用户>/.ssh/config` |
| macOS | `python3` | `chmod` | `/Users\<用户>\.ssh\config` |

| 远程OS | SSH配置路径 | 支持 |
|-----------|----------------|-----------|
| Ubuntu 18.04+ | `/etc/ssh/sshd_config` | ✅ |
| Debian 9+ | `/etc/ssh/sshd_config` | ✅ |
| CentOS 7+ | `/etc/ssh/sshd_config` | ✅ |
| RHEL 7+ | `/etc/ssh/sshd_config` | ✅ |
| Alpine Linux | `/etc/ssh/sshd_config` | ✅ |
| Windows Server | 不支持 | ❌ |

## 连接稳定性深入研究

### 问题：SSH断开连接

SSH连接在长时间运行操作期间可能断开，原因包括：

1. **空闲超时**
   - 防火墙在空闲后断开连接（通常60-300秒）
   - NAT网关过期会话映射
   - 服务器端空闲超时策略

2. **网络中断**
   - 临时丢包
   - 路由更改
   - ISP连接断开
   - WiFi切换

3. **TCP连接失败**
   - 没有应用程序级别的死连接检测
   - TCP keepalive禁用或太不频繁

### 解决方案架构

本技能实现了**双层防御**：

#### 第1层：SSH保活（预防）

**机制：**客户端定期向服务器发送null数据包

**配置（在步骤6中自动应用）：**
```
ServerAliveInterval 60      # 每60秒发送一次保活
ServerAliveCountMax 3       # 允许3次未响应（总共180秒）
TCPKeepAlive yes           # 启用TCP级保活
```

**工作原理：**
- 每60秒，SSH客户端发送一个保活数据包
- 如果服务器3次尝试（180秒）后仍未响应，连接被宣布死亡
- 防止防火墙/NAT断开空闲连接
- 对所有SSH命令透明工作

**限制：**
- 只能防止空闲超时
- 无法从网络中断中恢复
- 如果网络失败，连接仍然会断开

#### 第2层：tmux会话持久性（恢复）

**机制：**终端复用器在服务器上运行，会话在SSH断开后继续存在

**安装（在步骤3中自动完成）：**
```bash
apt-get install -y tmux
```

**工作原理：**
1. 在服务器上的分离tmux会话中启动命令
2. 命令在服务器进程空间运行（不是SSH会话）
3. 如果SSH断开，命令继续执行
4. 重新连接SSH并附加以查看进度

**使用模式：**

```bash
# 模式1：启动并分离
ssh server "tmux new-session -d -s deploy 'long_command'"

# 模式2：定期检查进度
ssh server "tmux capture-pane -t deploy -p | tail -50"

# 模式3：附加到交互式会话（如有需要）
ssh server -t "tmux attach -t deploy"

# 模式4：完成时终止
ssh server "tmux kill-session -t deploy"
```

**优点：**
- 完全不受SSH断开影响
- 命令在网络中断期间继续执行
- 可以故意分离/附加
- 可以同时运行多个会话
- 使用标准SSH工作（无需特殊端口/协议）

**何时使用tmux：**
- 操作需要超过2分钟
- 多步骤部署（git pull → build → restart）
- 大文件传输
- 数据库迁移
- 编译/构建过程

### 替代解决方案（不推荐）

#### autossh
- 自动重启SSH连接
- **问题：**不保留会话状态；正在运行的命令被终止
- **结论：**对隧道有用，不适合Claude Code的使用场景

#### Mosh（移动shell）
- 基于UDP，能在IP更改和网络中断中存活
- **问题：**需要开放UDP端口60000-61000，与标准SSH工具不兼容
- **结论：**对于边际收益来说太复杂

#### Eternal Terminal
- 具有会话保留功能的TCP重连
- **问题：**需要服务器守护进程、自定义端口，与Claude Code的Bash工具不兼容
- **结论：**对此使用场景过度工程化

#### SSH ControlMaster
- 重用单个SSH连接用于多个会话
- **问题：**如果主连接死亡，所有会话都死亡；不能解决断开问题
- **结论：**对性能好，对稳定性不好

### 最佳实践

1. **始终对部署使用tmux** - 即使在稳定网络上
2. **使用描述性名称命名会话** - `deploy`、`build`、`migration`，而不是`session1`
3. **非阻塞监控进度** - 使用`capture-pane`而不是`attach`
4. **清理旧会话** - 用`tmux ls`列出，用`tmux kill-session -t <名称>`终止不需要的
5. **测试保活设置** - 用`grep ServerAlive ~/.ssh/config`验证
6. **使用tmux_helper.py** - 简化会话管理

### 故障排除连接问题

**问题：连接在恰好60/120/300秒后断开**
- **原因：**防火墙空闲超时
- **解决方案：**已由ServerAliveInterval 60解决

**问题：长时间操作期间连接随机断开**
- **原因：**网络不稳定
- **解决方案：**对所有长操作使用tmux

**问题：重新连接后找不到tmux会话**
- **诊断：**`ssh server "tmux ls"`
- **原因：**会话被终止或从未启动
- **解决方案：**检查tmux日志，验证命令语法

**问题：多个tmux会话累积**
- **诊断：**`ssh server "tmux ls"`
- **解决方案：**终止旧会话：`ssh server "tmux kill-session -t <名称>"`

## 参考资料

- [OpenSSH手册](https://www.openssh.com/manual.html)
- [Paramiko文档](https://docs.paramiko.org/)
- [SSH配置文件格式](https://man.openbsd.org/ssh_config)
- [NTFS权限（icacls）](https://docs.microsoft.com/en-us/windows-server/administration/windows-commands/icacls)
- [tmux手册](https://man.openbsd.org/tmux)
- [SSH保活最佳实践](https://www.openssh.com/manual.html)
