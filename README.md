# GOLD INTELLIGENCE V1.2.2

国际黄金、国内金价与渠道比价仪表盘，支持 Streamlit Community Cloud 和 Mac 本地运行。入口为仓库根目录 `app.py`。

## 收益率最新数据与延迟核验（V1.2.2）

新增美国财政部当月XML直连，分别读取实际10年TC_10YEAR与名义2年BC_2YEAR、名义10年BC_10YEAR。财政部、H.15、FRED按观测日期选最新，同日财政部优先；旧来源新抓取成功不能让较新的观测日期倒退。短月初可补充上个月数据，当月网络故障不冒充上月数据已是最新。

关键收益率每15分钟检查。卡片和明细分别显示观测日、当前观测抓取时间、最近完成检查时间、来源标注更新时间或发布日期。XML updated按来源元数据标注，不冒充精确首次发布时间；未提供的发布时间明确标为未提供。

延迟状态区分已核验日度、可能延迟、检查失败使用缓存、核验已过期和来源返回旧数据。参考纽约时间17:00、美国联邦假日/周末及Good Friday估计应有的观测日，临时休市或发布延误以官方说明为准；该基准不是逐笔实时行情承诺。

[财政部XML官方说明](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed)

## 收益率修复（V1.2.1）

首页显示10年期实际收益率（TIPS）和2年期名义收益率，标注相对上一有效观测日的上升、下降或持平，以及变化基点与观测日期。宏观指标页新增三条美债收益率的曲线和明细，包括10年期名义收益率。

关键收益率不再等待FRED宏观批量下载：独立获取DFII10、DGS2单项CSV，并通过美联储H.15官方日度发布补充。H.15中的名义与通胀保值国债（TIPS）行分开解析，绝不用名义值填补实际收益率。合并同口径观测时保留来源，较新采集值修订重叠日期。

收益率每天按官方发布频率更新，网站每15分钟检查；不是盘中实时报价。变化按相邻有效观测值计算，1基点=0.01个百分点，未发布日和缺值不补0。备用源只有数日时会注明样本不足，不伪造长历史。

数据定义：[FRED DFII10](https://fred.stlouisfed.org/series/DFII10)、[FRED DGS2](https://fred.stlouisfed.org/series/DGS2)、[美联储H.15官方发布及口径](https://www.federalreserve.gov/releases/h15/)。

## 功能

- 国际黄金：Gold API 现货参考报价；COMEX `GC=F` 期货日线、技术指标与统计预测分开标注。Yahoo公共请求失败时尝试一次yfinance备用抓取，仍失败则退避。
- 国内走势：上海黄金交易所 Au99.99 最近30个自然日内已公布的人民币元/克日收盘价。
- 国内渠道：SMM 品牌黄金、金条、回收与换购公开挂牌价，按类别、成色、日期和客户交易方向分别比较。
- 彩色比价：鲜绿为组内最低价，亮红为最高价，金黄为中间价或同价；并列价格同时标注，旧日期不混入当前排名。支持CSV导出。
- 银行积存金：支持手动录入建行、工行、农行、中行、招行、交行及其他渠道的报价；明确标注未核验，与公开挂牌分开比较。银行自动报价尚未接入。
- 宏观与新闻：FRED九项指标，GDELT、BBC World、美联储和BLS官方RSS独立更新。
- 后台采集：并行请求、成功数据缓存、失败退避、观测时间与采集时间分开显示。单个来源故障不会阻止其他模块展示。

## 云端部署

Streamlit 应用指向本仓库 `main` 分支，入口 `app.py`。需要同时保留 `gold_intelligence/`、`requirements.txt` 和 `.streamlit/config.toml`，不要只复制入口文件。

依赖自动根据 requirements.txt 安装；无需付费AI密钥。云端配置使用平台默认监听地址。

云端本地缓存保存在实例的 `data/cache/`，休眠、重建或替换实例后可能丢失。报价源在不同网络环境可能超时，查看“数据诊断”了解具体连接状态。

## 本地运行

建议Python 3.11或更新版本。Mac可双击 `启动.command`，也可执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address=127.0.0.1
```

测试及取数诊断：

```bash
python -m unittest discover -s tests -v
python 诊断数据源.py
```

完整缓存页面测试需要先运行取数诊断，没有缓存时会跳过；其他回归测试可离线运行。

## 报价与模型口径

挂牌价可能不含工费、手续费、地区优惠，不能视作最终到手价。高低标记仅表示所选可比组内的数值大小。银行手动报价按同日、同方向、同成色、距组内最新报价15分钟内比较；记录保存在当前浏览器会话，可导出JSON。

上金所走势图不是国际金价换算。品牌挂牌源为第三方SMM汇总，不是品牌官方报价接口。现货与期货不会混成同一价格序列。

预测沿用V1的Ridge日线统计模型，周期按交易日标注，尚未完成各周期区间覆盖率或事件幅度回测。宏观历史值可能修订，标题规则仅表示传导假设。

## 数据来源

[上金所每日行情](https://www.sge.com.cn/sjzx/quotation_daily_new) · [SMM品牌挂牌表](https://precious.smm.cn/gold-price) · [Gold API](https://gold-api.com/docs) · [Yahoo Finance](https://finance.yahoo.com/) · [FRED](https://fred.stlouisfed.org/) · [GDELT](https://www.gdeltproject.org/) · [BBC World RSS](https://feeds.bbci.co.uk/news/world/rss.xml) · [美联储RSS](https://www.federalreserve.gov/feeds/feeds.htm) · [BLS RSS](https://www.bls.gov/feed/)
