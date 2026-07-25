# Windows免Docker部署指南

> ✅ 已验证：Windows 10/11 + Python 3.10+ + EnergyPlus 26.1.0

## 为什么不用Docker？

原版 EnergyPlus-MCP 要求 Docker Desktop，但：
- Docker Desktop在Windows上需WSL2，占用4GB+内存
- 高校/企业内网环境常限制Docker
- 中国用户下载Docker镜像速度慢

**本方案：纯Python本地部署，零容器依赖。**

---

## 步骤

### 1. 安装EnergyPlus 26.1.0

从 [NREL GitHub Releases](https://github.com/NREL/EnergyPlus/releases/tag/v26.1.0) 下载：
- `EnergyPlus-26.1.0-6f2e40d102-Windows-x86_64.zip`
- 解压到 `C:\EnergyPlusV26-1-0\`

### 2. 安装Python依赖

```powershell
pip install eppy matplotlib networkx pandas plotly graphviz mcp python-dotenv
```

### 3. 设置环境变量

```powershell
# PowerShell (永久)
[Environment]::SetEnvironmentVariable("EPLUS_IDD_PATH", "C:\EnergyPlusV26-1-0\Energy+.idd", "User")
[Environment]::SetEnvironmentVariable("EPLUS_INSTALLATION_PATH", "C:\EnergyPlusV26-1-0", "User")

# CMD (临时)
set EPLUS_IDD_PATH=C:\EnergyPlusV26-1-0\Energy+.idd
```

### 4. 启动服务器

```bash
cd energyplus-mcp-server
set PYTHONPATH=.
python -m energyplus_mcp_server.server
```

成功标志：
```
EnergyPlus MCP Server 'energyplus-mcp-server' v0.1.0 initialized
```

---

## 配置MCP客户端

### Hermes Agent

```bash
hermes config set mcp_servers.energyplus.command "C:/path/to/python.exe"
hermes config set mcp_servers.energyplus.args '["-m", "energyplus_mcp_server.server"]'
hermes config set mcp_servers.energyplus.enabled true
hermes config set mcp_servers.energyplus.env.EPLUS_IDD_PATH "C:/EnergyPlusV26-1-0/Energy+.idd"
hermes config set mcp_servers.energyplus.env.PYTHONPATH "C:/path/to/energyplus-mcp-server"
hermes config set mcp_servers.energyplus.workdir "C:/path/to/energyplus-mcp-server"
```

### Claude Desktop

见原版README的 Claude Desktop 配置（需Docker，不推荐Windows）。

### Cursor / VS Code

见原版README。

---

## 常见问题

| 问题 | 解决 |
|------|------|
| `IDD file not found` | 确认 `EPLUS_IDD_PATH` 指向正确路径 |
| `energyplus executable not found` | 仅影响模拟工具，模型分析工具不受影响 |
| `graphviz not found` | `pip install graphviz` |
| `uv sync` 失败 (PE资源错误) | 改用 `pip install`，uv在Windows上有已知问题 |

---

## 验证安装

```python
from energyplus_mcp_server.energyplus_tools import EnergyPlusManager
from energyplus_mcp_server.config import Config

config = Config()
config.energyplus.idd_path = r'C:\EnergyPlusV26-1-0\Energy+.idd'
config.paths.workspace_root = r'C:\path\to\energyplus-mcp-server'
mgr = EnergyPlusManager(config)

# 加载示例模型
result = mgr.load_idf('1ZoneUncontrolled.idf')
print(f"✅ {result['zone_count']} zones loaded")
```
