# GOLD INTELLIGENCE V1.0（Mac 本地版）

本项目是国际黄金智能分析仪表盘的第一版，优先使用免费公开数据。

## 功能
- 国际黄金行情：优先 Yahoo Finance `XAUUSD=X`；不可用时回退 `GC=F`（COMEX期货代理，不是现货）。
- 盘中参考报价：尝试 Yahoo 5分钟数据；不可用时显示最近日线收盘。
- 市场驱动：DXY、美国10年期名义收益率、VIX、WTI、GLD、USD/CNY（有数据时）。
- FRED宏观指标：DFII10、DGS10、T10YIE、CPIAUCSL、PCEPI、UNRATE、FEDFUNDS、PAYEMS。
- GDELT国际新闻：标题去重、事件分类、因果路径、方向与验证条件。
- 量化预测：时间顺序验证的 Ridge 多因子模型，输出24小时、3天、7天、30天、90天中心预测及80%/95%区间和方向概率。
- 技术指标：RSI、MA20、MA50、20日年化波动率。

## 重要限制
1. 免费不等于实时。Yahoo Finance 免费行情可能延迟、限流或改变接口；5分钟数据不保证逐笔实时。
2. yfinance 是非官方 Yahoo Finance 数据访问库，不代表 Yahoo 官方支持。
3. CPI、PCE、失业率、非农就业等按月度发布；实际收益率等部分指标按日度发布。
4. FRED `fredgraph.csv` 是图表 CSV 下载路径，不等于稳定承诺的 API。若不可用，后续可切换到免费的 FRED API Key。
5. GDELT 新闻覆盖不完整，标题分类可能误判。
6. 事件卡片不会凭新闻标题编造涨跌幅。V1的价格区间由历史行情模型计算；事件特定冲击幅度需下一阶段建立历史事件样本并回测。
7. 模型输出不保证准确，不构成投资建议。

## 安装与启动
建议 Python 3.11 或 3.12。

### 最简单方式
1. 解压 ZIP。
2. 进入 `gold_intelligence_v1` 文件夹。
3. 双击 `启动.command`。
4. 第一次启动会自动创建虚拟环境、安装依赖并运行。
5. 浏览器访问 `http://localhost:8501`。

若 macOS 阻止脚本：右键 `启动.command` → 打开。

### 终端方式
```bash
cd ~/Downloads/gold_intelligence_v1
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python -m streamlit run app.py
```
停止运行：回到终端按 `Control + C`。

## 后续版本
- 经济日历：预期值、实际值、前值和公布时间。
- 历史事件研究：估算事件后1小时、1天、3天、5天的异常收益。
- 模型滚动回测：方向准确率、区间覆盖率、基准模型对比、模型漂移。
- 加入人民币/克换算和用户积存金持仓管理。
