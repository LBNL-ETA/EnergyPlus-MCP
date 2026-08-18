# EnergyPlus-MCP — AI × Building Energy Simulation

> **The first open-source Model Context Protocol (MCP) server that lets AI assistants interact programmatically with EnergyPlus — now with a desktop GUI for everyone.**

[![License](https://img.shields.io/badge/license-BSD--3--Clause--LBNL-blue.svg)](License.txt)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![Release](https://img.shields.io/github/v/release/yaowanxiang/EnergyPlus-MCP)](https://github.com/yaowanxiang/EnergyPlus-MCP/releases)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#)

---

## English Introduction

### What is EnergyPlus-MCP?

**EnergyPlus-MCP** is an open-source [Model Context Protocol](https://modelcontextprotocol.io) server that bridges AI assistants (Claude, Cursor, Codex, Hermes, etc.) with the [EnergyPlus](https://energyplus.net) building energy simulation engine.

Instead of manually editing IDF files, an AI assistant can now:
- **Read and inspect** IDF models — zones, surfaces, materials, schedules, people, lights, electric equipment
- **Modify** building systems programmatically (people, lights, equipment, schedules, output variables/meters)
- **Run and manage** simulations, inspect output meters and variables
- **List and copy** sample files and weather data

### Desktop GUI (New in v0.2)

A graphical desktop client (Windows / macOS / Linux) is now included:

- 🔍 **Auto-detect** EnergyPlus installations on your machine (common paths)
- ⚙️ **Configure** installation / executable / IDD / weather paths — saved to config.json
- 🚀 **One-click start** the MCP HTTP server (default port 8631)
- 🧰 **Browse** all 20+ tool capabilities
- ✅ **Verify** your EnergyPlus installation with one click

Then point your AI assistant at `http://127.0.0.1:8631/mcp` and ask it to read your IDF, inspect zones, or run simulations — no coding needed.

### Installers (auto-built on every tag)

| Platform | Installer |
|---|---|
| Windows | `EnergyPlus-MCP-Windows-x64.exe` |
| macOS | `EnergyPlus-MCP-macOS.dmg` |
| Linux | `EnergyPlus-MCP-Linux-x86_64.AppImage` |

### Quick Start

**Option 1 — Desktop GUI (recommended):**
```bash
# Download the installer for your platform from Releases, then:
python gui/app.py            # or double-click the packaged app
# Click "检测" → "保存配置" → "启动 MCP 服务"
```

**Option 2 — MCP server (stdio / streamable-http):**
```bash
cd energyplus-mcp-server
pip install -e .
export TRANSPORT=streamable-http    # or stdio
python -m energyplus_mcp_server
```

**Option 3 — CLI (stdin/stdout):**
```bash
npx @modelcontextprotocol/inspector python -m energyplus_mcp_server
```

### Architecture

```
EnergyPlus-MCP/
├── gui/                       # Desktop GUI (pywebview + FastAPI)
│   ├── app.py                 # GUI entry: env detection, config, MCP control
│   └── web/index.html         # GUI frontend (self-contained)
├── energyplus-mcp-server/     # MCP server (FastMCP)
│   ├── energyplus_mcp_server/
│   │   ├── server.py          # FastMCP server (stdio / streamable-http)
│   │   ├── http_app.py        # Starlette HTTP app with auth
│   │   ├── energyplus_tools.py# EnergyPlusManager — 20+ simulation tools
│   │   ├── config.py          # EnergyPlus / transport / auth config
│   │   └── utils/             # meters, variables, schedules, diagrams…
│   └── illustrative examples/ # 5ZoneAirCooled etc.
├── build.py                   # Cross-platform packaging (PyInstaller)
└── .github/workflows/release.yml  # Auto-build 3 platforms on tag push
```

### License

BSD-3-Clause-LBNL © 2025 The Regents of the University of California, through Lawrence Berkeley National Laboratory.

---
---

# 🇨🇳 中文版介绍

## EnergyPlus-MCP —— 让 AI 直接操作建筑能耗模拟

> **首个开源的 Model Context Protocol (MCP) 服务器，让 AI 助手（Claude / Cursor / Codex / Hermes 等）能以编程方式与 EnergyPlus 建筑能耗模拟引擎交互。现在配上了人人可用的图形化界面。**

### 它能做什么？

**EnergyPlus-MCP** 是一座桥：把 AI 助手和 EnergyPlus 模拟引擎连起来。AI 现在可以：

- **读取与检查** IDF 模型 —— 分区、表面、材料、日程、人员、灯光、电气设备
- **程序化修改** 建筑系统（人员 / 灯光 / 设备 / 日程 / 输出变量与计量表）
- **运行与管理** 模拟，查看输出计量表和变量
- **列出与复制** 示例文件和天气数据

### 🖥️ 图形化界面（v0.2 新增）

桌面客户端（Windows / macOS / Linux 三平台）：

- 🔍 **自动检测** 本机 EnergyPlus 安装（常见路径）
- ⚙️ **配置管理** 安装路径 / 可执行文件 / IDD / 天气文件 —— 保存到 config.json
- 🚀 **一键启动** MCP HTTP 服务（默认端口 8631）
- 🧰 **浏览全部** 20+ 项工具能力
- ✅ **一键验证** EnergyPlus 安装是否可用

然后把 AI 助手指向 `http://127.0.0.1:8631/mcp`，直接问它"读取 5ZoneAirCooled.idf 的模型信息"——不需要写任何代码。

### 📦 安装包（打 tag 自动构建三平台）

| 平台 | 安装包 |
|---|---|
| Windows | `EnergyPlus-MCP-Windows-x64.exe` |
| macOS | `EnergyPlus-MCP-macOS.dmg` |
| Linux | `EnergyPlus-MCP-Linux-x86_64.AppImage` |

### 🚀 快速开始

**方式一 · 图形界面（推荐）：**
```bash
# 从 Releases 下载对应平台安装包，然后：
python gui/app.py            # 或直接双击打包好的应用
# 点「重新检测」→「保存配置」→「启动 MCP 服务」
```

**方式二 · MCP 服务器（stdio / streamable-http）：**
```bash
cd energyplus-mcp-server
pip install -e .
export TRANSPORT=streamable-http    # 或 stdio
python -m energyplus_mcp_server
```

**方式三 · 命令行调试：**
```bash
npx @modelcontextprotocol/inspector python -m energyplus_mcp_server
```

### 架构

```
EnergyPlus-MCP/
├── gui/                       # 桌面图形界面（pywebview + FastAPI）
│   ├── app.py                 # GUI 入口：环境检测、配置、MCP 控制
│   └── web/index.html         # 前端页面（自包含）
├── energyplus-mcp-server/     # MCP 服务器（FastMCP）
│   ├── energyplus_mcp_server/
│   │   ├── server.py          # FastMCP 服务（stdio / streamable-http）
│   │   ├── http_app.py        # Starlette HTTP 应用（带鉴权）
│   │   ├── energyplus_tools.py# EnergyPlusManager —— 20+ 模拟工具
│   │   ├── config.py          # EnergyPlus / 传输 / 鉴权配置
│   │   └── utils/             # 计量表、变量、日程、图表…
│   └── illustrative examples/ # 5ZoneAirCooled 等示例
├── build.py                   # 跨平台打包（PyInstaller）
└── .github/workflows/release.yml  # 打 tag 自动构建三平台并发布
```

### 许可证

BSD-3-Clause-LBNL © 2025 加州大学校董会（通过劳伦斯伯克利国家实验室）。

---

**EnergyPlus-MCP —— 让每个建筑工程师，都能用自然语言驱动能耗模拟。**
