# SSH远控 - 快速入门模板

这是一个包含参数占位符的简明执行指南，用于快速参考。

## 前置要求

```bash
python -m pip install paramiko -q
```

## 参数

执行前替换这些占位符：

- `{{SERVER_IP}}` - 服务器IP地址（例如：`154.217.245.99`）
- `{{USERNAME}}` - SSH用户名（例如：`root`、`ubuntu`）
- `{{PASSWORD}}` - SSH密码
- `{{ALIAS}}` - 期望的SSH别名（例如：`server1`、`devserver`）

## 执行步骤

### 1. 测试连接并启用公钥认证

```bash
python ssh-remote-control/scripts/setup_ssh_auth.py {{SERVER_IP}} {{USERNAME}} {{PASSWORD}}
```

### 2. 生成SSH密钥

```bash
python ssh-remote-control/scripts/generate_ssh_key.py {{SERVER_IP}}
```

### 3. 上传公钥

```bash
python ssh-remote-control/scripts/upload_ssh_key.py {{SERVER_IP}} {{USERNAME}} {{PASSWORD}}
```

### 4. 完成配置

```bash
python ssh-remote-control/scripts/finalize_ssh_config.py {{SERVER_IP}} {{USERNAME}} {{ALIAS}}
```

### 5. 验证连接

```bash
ssh {{ALIAS}} "whoami && hostname"
```

## 日常使用

```bash
# 执行命令
ssh {{ALIAS}} "ls -lh /var/www"

# 上传文件
scp local.txt {{ALIAS}}:/remote/path/

# 下载文件
scp {{ALIAS}}:/remote/file.txt ./

# 使用tmux运行长时间任务（推荐用于部署）
ssh {{ALIAS}} "tmux new-session -d -s deploy 'cd /app && npm install && npm run build'"
ssh {{ALIAS}} "tmux capture-pane -t deploy -p | tail -50"
```

## 快速故障排除

| 错误 | 解决方案 |
|-------|----------|
| `REMOTE HOST IDENTIFICATION HAS CHANGED` | `ssh-keygen -R {{SERVER_IP}}` |
| `Permissions 0644 are too open` | 重新运行步骤4 |
| `Permission denied (publickey)` | 检查 `ssh {{ALIAS}} "cat ~/.ssh/authorized_keys"` |

## 示例：完整设置

```bash
# 安装paramiko
python -m pip install paramiko -q

# 为服务器154.217.245.99设置
python ssh-remote-control/scripts/setup_ssh_auth.py 154.217.245.99 root mypassword123
python ssh-remote-control/scripts/generate_ssh_key.py 154.217.245.99
python ssh-remote-control/scripts/upload_ssh_key.py 154.217.245.99 root mypassword123
python ssh-remote-control/scripts/finalize_ssh_config.py 154.217.245.99 root myserver

# 测试
ssh myserver "whoami"
```

## 成功指标

- ✅ 步骤1：显示"✓ 连接成功"和服务器信息
- ✅ 步骤2：显示"✓ 密钥生成成功"和公钥
- ✅ 步骤3：显示"✓ 公钥已上传"和指纹
- ✅ 步骤4：显示"✓ SSH别名已配置连接保活"
- ✅ 步骤5：返回用户名且无密码提示

## 连接稳定性功能

此设置包含自动连接稳定性：
- **SSH保活**：防止空闲超时（60秒间隔，3次重试）
- **tmux**：在服务器上安装以在断开连接时保持会话持久性
- 对于超过2分钟的任何操作使用tmux

## 长时间任务：git clone / docker pull / docker build

这类任务耗时可能超过10分钟，**必须在 tmux 里运行**，否则网络抖动会导致任务中断。

```bash
# 连接服务器后先进 tmux
ssh {{ALIAS}}
tmux new -s work

# 在 tmux 里正常执行
git clone https://github.com/xxx/yyy.git
docker pull some-image:latest
docker build -t myapp .

# 需要暂时离开时：Ctrl+B 然后 D（任务继续在后台跑）
# 重新进入查看进度
ssh {{ALIAS}}
tmux attach -t work
```

| 操作 | 命令 |
|------|------|
| 新建 session | `tmux new -s work` |
| 暂时离开（任务继续） | `Ctrl+B` 然后 `D` |
| 重新进入 | `tmux attach -t work` |
| 查看所有 session | `tmux ls` |
| 关闭 session | `tmux kill-session -t work` |

**原则：只要任务预计超过 2 分钟，就在 tmux 里跑。**
