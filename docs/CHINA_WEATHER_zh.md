# 🌤️ 324中国城市CSWD天气数据

## 数据来源

中国标准气象数据 (CSWD)，专为中国建筑热环境分析定制。

## 覆盖范围

- **34个省级行政区** 全覆盖
- **324个气象站点**
- 每个站点包含：`.epw`（全年逐时） + `.stat`（统计） + `.ddy`（设计日）

## 下载

从 [energyplus.net/weather](https://energyplus.net/weather) 搜索中国城市下载。

已下载zip包 → 解压到 `C:\EnergyPlusV26-1-0\WeatherData\`。

## 山东站点（9个）

| 站点 | 文件名 |
|------|--------|
| 济南 | `CHN_Shandong.Jinan.548230_CSWD.epw` |
| 潍坊 | `CHN_Shandong.Weifang.548430_CSWD.epw` |
| 龙口 | `CHN_Shandong.Longkou.547530_CSWD.epw` |
| 兖州 | `CHN_Shandong.Yanzhou.549160_CSWD.epw` |
| 惠民 | `CHN_Shandong.Huimin.Xian.547250_CSWD.epw` |
| 成山头 | `CHN_Shandong.Chengshantou.547760_CSWD.epw` |
| 朝阳 | `CHN_Shandong.Chaoyang.548080_CSWD.epw` |
| 莒县 | `CHN_Shandong.Juxian.549360_CSWD.epw` |

⚠️ **青岛不在CSWD数据集中**。最近替代站：济南（省会，气候相似）或潍坊。

## 使用

```python
# 用济南天气模拟建筑能耗
result = mgr.run_simulation(
    'my_building.idf',
    'CHN_Shandong.Jinan.548230_CSWD.epw'
)
```

## 其他数据源

- **IWEC**: 国际典型年（北京/哈尔滨/昆明/兰州/上海/沈阳/乌鲁木齐）
- **SWERA**: 太阳能/风能资源评估（50+中国站点）
