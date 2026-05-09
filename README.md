# GCP-Manager-V3.4

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.7%2B-blue.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.0%2B-green.svg)](https://pypi.org/project/PyQt6/)

一个功能强大的 GCP (Google Cloud Platform) 批量实例管理工具，支持批量创建、管理、监控 GCP 虚拟机实例，内置 Root 密码模式和 SSH 密钥模式，一键防火墙配置等高级功能。

## 🌟 主要特性

### 🚀 批量管理
- **批量创建实例** - 支持多账号批量创建，自动区域配额管理，智能选择可用区域
- **批量操作** - 支持批量删除、启动、停止、重启实例
- **批量导入** - 支持批量导入 JSON 格式的 GCP 服务账号
- **区域管理** - 智能分配免费区域（最多4台/区域），支持付费区域选择

### 🔐 身份认证
- **Root 密码模式**
  - 用户自定义密码：手动设置 root 登录密码
  - 自动随机密码：自动生成 16 位强密码，明文显示便于复制
  - 自动配置 SSH 服务：开启密码认证和 root 登录
- **SSH 密钥模式**
  - 公钥上传：支持上传 SSH 公钥文件
  - 自动注入：将公钥注入到项目级 ssh-keys 元数据
  - 安全登录：通过私钥安全登录

### 🛡️ 网络安全
- **一键防火墙** - 自动创建入站和出站允许所有流量的防火墙规则
- **代理支持** - 支持 HTTP/SOCKS 代理，支持批量导入代理配置
- **实时监控** - 支持哪吒监控面板集成，实时显示实例监控状态

### 💡 用户体验
- **双击复制** - 双击 IP 列或 Root 密码列快速复制，日志实时反馈
- **实时日志** - 所有操作都有详细的执行日志，便于排查问题
- **状态显示** - 实例状态实时更新，支持自动刷新
- **界面友好** - 基于 PyQt6 的现代化界面，操作直观

## 📦 安装指南

### 环境要求
- **操作系统**: Windows 10/11
- **Python**: 3.7 或更高版本
- **内存**: 推荐 4GB 以上
- **网络**: 需要访问 Google Cloud API

### 依赖安装

```bash
# 安装 Python 依赖
pip install google-cloud-compute PyQt6 requests

# 或者使用 requirements.txt
pip install -r requirements.txt
```

### 打包为独立可执行文件

```bash
# 多文件模式（推荐，启动更快）
pyinstaller --onedir --noconsole --windowed --icon "GCP_Manager_v3.3.ico" --name "GCP批量管理工具v3.4" "GCP_Manager_v3.4.py"

# 单文件模式（便于分发）
pyinstaller --onefile --noconsole --windowed --icon "GCP_Manager_v3.3.ico" --name "GCP批量管理工具v3.4" "GCP_Manager_v3.4.py"
```

## 🚀 快速开始

### 1. 准备 GCP 服务账号
1. 登录 [Google Cloud Console](https://console.cloud.google.com/)
2. 创建服务账号并下载 JSON 密钥文件
3. 确保服务账号有 `Compute Instance Admin` 权限

### 2. 启动程序
```bash
python GCP_Manager_v3.4.py
```

### 3. 添加账号
1. 点击"添加账号"
2. 填写邮箱地址
3. 选择 JSON 密钥文件
4. 可选择配置代理
5. 点击"保存"

### 4. 创建实例
1. 选择要使用的账号（勾选）
2. 选择创建模式：
   - **SSH 密钥模式**：上传 SSH 公钥文件
   - **Root 密码模式**：选择自定义密码或随机密码
3. 选择区域：
   - **免费区**：自动在 us-central1/us-east1/us-west1 中随机选择
   - **付费区**：选择特定付费区域
4. 设置实例数量
5. 点击"开始部署"

## 📋 详细功能说明

### Root 密码模式详解

#### 创建流程
1. 用户选择 Root 密码模式
2. 选择密码类型：
   - **用户自定义密码**：手动输入密码
   - **自动随机密码**：生成 16 位包含大小写字母、数字、特殊字符的密码
3. 程序注入 startup-script：
   ```bash
   #!/bin/bash
   set -euxo pipefail
   # 设置 root 密码
   echo 'root:密码' | chpasswd
   # 解锁 root 账户
   passwd -u root || true
   # 配置 SSH
   sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin yes/g' /etc/ssh/sshd_config
   sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/g' /etc/ssh/sshd_config
   # 清空可能的冲突配置
   rm -rf /etc/ssh/sshd_config.d/* /etc/ssh/ssh_config.d/*
   # 重启 SSH 服务
   systemctl restart ssh || systemctl restart sshd
   ```

#### 密码显示
- **随机密码模式**：创建成功后密码明文显示在日志和实例列表中
- **自定义密码模式**：日志显示"密码模式：用户自定义"，列表显示"用户自定义"

### SSH 密钥模式详解

#### 公钥注入流程
1. 用户上传 SSH 公钥文件
2. 程序将公钥以 `root:公钥内容` 格式写入项目级 ssh-keys 元数据
3. 创建实例时自动注入该公钥
4. 用户可用对应的私钥登录

### 哪吒监控集成

#### 配置步骤
1. 在哪吒监控配置面板中：
   - 面板地址：如 `https://nezha.example.com`
   - Token：面板的访问令牌
2. 点击"保存配置"
3. 点击"刷新数据"获取监控信息

#### 功能特性
- 自动匹配实例 IP 与监控面板中的设备
- 在实例列表中显示监控名称
- 支持实时刷新监控状态

### 代理配置支持

#### 支持的代理格式
```
http:IP:PORT:USER:PASS
https:IP:PORT:USER:PASS
socks:IP:PORT:USER:PASS
socks5:IP:PORT:USER:PASS
http://USER:PASS@IP:PORT
https://USER:PASS@IP:PORT
socks://USER:PASS@IP:PORT
socks5://USER:PASS@IP:PORT
```

#### 使用方式
1. 在添加账号时配置代理
2. 支持批量导入代理配置
3. 所有操作都会通过代理执行

## 🔧 高级配置

### 区域配额管理
- **免费区域限制**：每个区域最多 4 台实例
- **智能分配**：自动选择有配额的区域
- **区域优先级**：us-central1 > us-east1 > us-west1

### 防火墙配置
- **入站规则**：允许所有 IP、所有协议、所有端口
- **出站规则**：允许所有 IP、所有协议、所有端口
- **规则名称**：allow-all-ingress 和 allow-all-egress

### 自动刷新机制
- 批量创建完成后自动刷新实例列表
- 实例操作完成后自动刷新状态
- 支持手动刷新查询

## 🐛 故障排除

### 常见问题

#### Q: 创建实例时提示"资源耗尽"
**A**: 该区域配额已满，程序会自动切换到其他区域。

#### Q: Root 密码模式无法登录
**A**: 
1. 确保创建后等待 1-2 分钟让启动脚本执行完成
2. 检查实例状态是否为 RUNNING
3. 尝试使用 SSH 密钥模式作为备选方案

#### Q: 代理连接失败
**A**: 
1. 检查代理格式是否正确
2. 确认代理服务是否正常运行
3. 尝试不使用代理测试

#### Q: 哪吒监控无法获取数据
**A**: 
1. 检查面板地址和 Token 是否正确
2. 确认网络连接是否正常
3. 点击"测试连接"按钮验证

### 日志分析
程序提供详细的操作日志，包含：
- 时间戳
- 操作类型
- 执行结果
- 错误信息
- IP 地址信息

## 📊 性能优化

### 批量创建优化
- **并发控制**：最多 3 个线程同时创建
- **智能重试**：遇到资源耗尽自动重试其他区域
- **日志记录**：每台实例的创建状态都有详细记录

### 内存管理
- **实例缓存**：实例信息本地缓存，减少 API 调用
- **UI 优化**：表格虚拟滚动，支持大量实例显示
- **资源清理**：定期清理过期缓存数据

## 🤝 贡献指南

### 开发环境设置
```bash
# 克隆仓库
git clone https://github.com/shenping1200/GCP-Manager-V3.4.git
cd GCP-Manager-V3.4

# 安装依赖
pip install -r requirements.txt

# 运行测试
python GCP_Manager_v3.4.py
```

### 代码规范
- 使用 PEP 8 Python 代码规范
- 添加适当的注释和文档字符串
- 确保所有功能都有相应的测试

### 提交规范
- 使用清晰的提交信息
- 遵循 Git Flow 工作流程
- 确保代码经过充分测试

## 📝 更新日志

### v3.4 (2026-05-09)
- ✨ **新增 Root 密码模式**
  - 支持用户自定义密码
  - 支持自动随机密码生成
  - 自动配置 SSH 服务
- ✨ **新增双击复制功能**
  - 双击 IP 列快速复制 IP
  - 双击 Root 密码列快速复制密码
  - 日志实时反馈复制结果
- 🔧 **优化启动脚本**
  - 强化 SSH 配置
  - 清理冲突配置文件
  - 增加错误处理机制
- 🐛 **修复已知问题**
  - 修复实例列表显示问题
  - 优化代理连接稳定性

### v3.3 (2026-05-08)
- 🎨 **UI 优化**
  - 采用 2.27 版本界面风格
  - 优化按钮和布局设计
- 🔧 **功能完善**
  - 完善防火墙创建逻辑
  - 优化批量操作流程

### v3.2 (2026-05-08)
- 🚀 **稳定性提升**
  - 修复多线程 UI 交互问题
  - 优化异常处理机制
- 🔧 **功能增强**
  - 支持批量导入代理
  - 完善错误提示信息

### v3.1 (2026-05-08)
- 🆓 **免费区域管理**
  - 智能配额分配
  - 随机区域选择
- 🔧 **界面优化**
  - 改进区域选择逻辑

## 📄 许可证

本项目采用 [MIT 许可证](LICENSE)，详见 LICENSE 文件。

## 👤 作者

- **作者**: shenping1200
- **GitHub**: [shenping1200](https://github.com/shenping1200)
- **邮箱**: shenping1200@users.noreply.github.com

## 🙏 致谢

感谢所有贡献者和用户的支持！

## 📞 支持

如果遇到问题或有建议，请：
1. 查看[故障排除](#故障排除)部分
2. 检查 [Issues](https://github.com/shenping1200/GCP-Manager-V3.4/issues) 页面
3. 提交新的 Issue 描述问题

---

**⭐ 如果这个工具对你有帮助，请给个 Star！**