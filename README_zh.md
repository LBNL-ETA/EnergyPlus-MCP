# 🏗️ EnergyPlus MCP Server · 建筑能耗模拟AI助手

[English](README.md) | **中文**

基于 Model Context Protocol (MCP) 的 EnergyPlus 建筑能耗模拟服务器，提供 **35个工具** 用于加载、验证、修改和分析 EnergyPlus IDF 文件。

## 🎯 核心功能

- 🏗️ **完整模型生命周期**: 加载、验证、分析、修改、模拟 IDF 文件
- 🔍 **深度建筑分析**: 提取 zone、表面、材料、时间表的详细信息
- 🚀 **自动模拟**: 使用天气文件执行 EnergyPlus 模拟
- 📊 **高级可视化**: 创建交互式图表和 HVAC 系统图
- 🔧 **HVAC 智能**: 发现、分析和可视化 HVAC 系统拓扑

## ⚡ 快速开始（Windows 免 Docker）

```powershell
# 1. 安装 EnergyPlus 26.1.0
# 从 https://github.com/NREL/EnergyPlus/releases 下载

# 2. 安装依赖
pip install eppy matplotlib networkx pandas plotly graphviz mcp python-dotenv

# 3. 设置环境变量
set EPLUS_IDD_PATH=C:\EnergyPlusV26-1-0\Energy+.idd

# 4. 启动
cd energyplus-mcp-server
set PYTHONPATH=.
python -m energyplus_mcp_server.server
```

## 🌤️ 中国天气数据

324个中国城市 CSWD 天气数据可从 [energyplus.net/weather](https://energyplus.net/weather) 下载。

详见 [docs/CHINA_WEATHER_zh.md](docs/CHINA_WEATHER_zh.md)。

## 🏫 建筑节能应用场景

| 方向 | 工具组合 |
|------|---------|
| 围护结构优化 | `get_materials` → `change_infiltration_by_mult` → `add_window_film_outside` |
| 热舒适分析 | `inspect_people` → `run_simulation` → `create_interactive_plot` |
| HVAC系统 | `discover_hvac_loops` → `visualize_loop_diagram` |

## 📚 详细文档

- [Windows免Docker部署指南](docs/WINDOWS_SETUP_zh.md)
- [中国天气数据](docs/CHINA_WEATHER_zh.md)

## 📄 引用

```bibtex
@article{li2025energyplusmcp,
  title={EnergyPlus-MCP: A Model Context Protocol Server for Building Energy Simulation},
  author={Li, Han and others},
  journal={SoftwareX},
  year={2025},
  publisher={Elsevier}
}
```

## 📜 License

BSD-3-Clause-LBNL © The Regents of the University of California
