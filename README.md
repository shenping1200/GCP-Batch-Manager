# GCP 批量管理工具 v3.4

GCP (Google Cloud Platform) 批量实例管理工具，支持批量创建、删除、启动、停止实例，内置 Root 密码模式，一键开启防火墙等功能。

## ✨ 特性

- **批量创建实例** - 支持多账号批量创建，自动区域配额管理
- **Root 密码模式** - 支持自定义密码或随机密码，创建后直接 root 登录
- **SSH 密钥模式** - 保留传统 SSH 公钥注入方式
- **一键防火墙** - 自动开启所有入站和出站规则
- **哪吒监控集成** - 支持哪吒监控面板配置和数据刷新
- **代理支持** - 支持 HTTP/SOCKS 代理，支持批量导入代理
- **批量操作** - 批量删除、启动、停止、重启实例
- **双击复制** - 双击 IP/密码列快速复制，日志实时反馈

## 📦 安装

### 依赖安装

```bash
pip install google-cloud-compute PyQt6 requests
```

### 打包为可执行文件

```bash
# 多文件模式
pyinstaller --onedir --noconsole --windowed --icon "GCP_Manager_v3.3.ico" --name "GCP_Manager_v3.4" "GCP_Manager_v3.4.py"

# 单文件模式
pyinstaller --onefile --noconsole --windowed --icon "GCP_Manager_v3.3.ico" --name "GCP_Manager_v3.4" "GCP_Manager_v3.4.py"
```

## 🚀 使用

1. 准备 GCP 服务账号 JSON 密钥
2. 运行程序，添加账号
3. 选择创建模式（SSH 密钥模式 或 Root 密码模式）
4. 配置区域和数量，点击开始部署

### Root 密码模式

- **用户自定义密码**: 手动设置 root 密码
- **自动随机密码**: 自动生成 16 位随机密码，明文显示在日志和列表

## ⚙️ 配置

### 哪吒监控

在"哪吒监控配置"面板填写：
- 面板地址
- Token

### 代理设置

支持格式：
- `http:IP:PORT:USER:PASS`
- `https:IP:PORT:USER:PASS`
- `socks:IP:PORT:USER:PASS`
- `socks5:IP:PORT:USER:PASS`
- `http://USER:PASS@IP:PORT`
- 等

## 📝 版本历史

- **v3.4** - Root 密码模式增强，双击复制功能
- **v3.3** - UI 风格优化
- **v3.2** - 稳定性增强，防火墙功能
- **v3.1** - 免费区域配额管理
- **v2.27** - 稳定基线版本

## 📄 许可证

MIT License

## 👤 作者

shenping1200

## 🙏 致谢

感谢所有贡献者！
