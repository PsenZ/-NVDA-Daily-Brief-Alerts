# VeyraQuant 量化交易助手

VeyraQuant 是一个面向美股波段交易的半自动量化交易助手。它会定时扫描股票池，结合市场环境、技术结构、新闻情绪、期权线索和风险预算，输出每天可复核的交易决策简报、机会提醒与风险提醒。

它不是自动交易机器人，也不会连接券商 API。它的核心目标不是替你下单，而是帮你更快、更稳定地回答三件事：

- 今天的市场环境是否支持进攻
- 现在最值得关注的是哪几只票
- 如果要做，应该如何定义入场、止损、目标位和仓位

## 核心亮点

### 1. 股票池扫描，而不是单票主观盯盘

通过 `SYMBOLS` 配置一组美股或 ETF，例如：

```text
NVDA,TSLA,AAPL,AMD,MU,QQQ,SMH
```

系统会逐个标的打分、排序、筛选，再输出当天真正值得执行或观察的对象，避免只盯着单一热门票。

### 2. 市场先过滤，再谈个股交易

VeyraQuant 先看大盘和板块环境，再决定是否允许进攻：

- `SPY`：大盘风险偏好
- `QQQ`：科技成长趋势
- `SMH`：半导体板块强弱
- `^VIX`：波动率压力

在风险规避环境下，系统会收紧批准数量和执行节奏，而不是机械地照单全收高分信号。

### 3. 多维度打分，但不是黑箱

每个标的的综合判断来自多个可解释维度：

- 趋势结构：MA5 / MA10 / MA20 / MA50 / MA200，20 日与 55 日高低点
- 动量状态：RSI、MACD、ADX、DI
- 相对强弱：相对 `SPY` / `QQQ` 的表现
- 成交量确认：5 日和 20 日量能比较
- 波动与期权：ATR、隐含波动率、Put/Call 比率
- 新闻与情绪：RSS、Google News、公开标题情绪
- 事件风险：收入增长、分析师一致预期
- 纪律过滤：反追高、负面舆情 veto、市场 risk-off veto

它给你的不是一句“买 / 不买”，而是一套有来由的判断。

### 4. 从分数驱动升级为论证驱动

系统现在不再只依赖单一总分直接落地，而是把每个最终结果拆成：

- `bull_case`：为什么现在值得做
- `bear_case`：最大的反方风险是什么
- `rating`：`Buy / Overweight / Hold / Underweight / No Trade`
- `action`：`BUY_TRIGGER / ADD_TRIGGER / WATCH / WAIT / RISK_REDUCE / REJECT`
- `conviction_level`：`high / medium / low`
- `decision_balance`：多空结构是否偏向一致还是脆弱

这让输出更像真实交易台的研究与决策过程，而不是单一信号灯。

### 5. 新增组合审批层，而不是把所有高分票都塞进日报

在原始信号之上，系统增加了规则型 `Portfolio Manager` 审批层：

- 同板块候选过多时，只保留更强的 1-2 个
- `risk-off` 环境下降低当日批准数量
- 组合 heat 紧张时，优先保留更干净、更高 conviction 的计划
- `WATCH / WAIT / RISK_REDUCE / REJECT` 不会混进可执行计划列表

这一步非常重要，因为真实交易里最难的问题往往不是“有没有信号”，而是“今天先做谁”。

### 6. 交易计划先校验，再进入结果对象

只有最终 `actionable` 的结果才允许保留完整交易计划。系统会在计划生成后做最后一层有效性校验：

- RR 不得低于 `MIN_RR`
- 仓位不得超过 `MAX_POSITION_PCT`
- 最大亏损不得超过 `RISK_PER_TRADE_PCT`
- 过宽的 entry zone 先给 warning，再对明显异常区间做 reject

也就是说，日报里出现的可执行计划，不只是“像机会”，还必须先通过内部风控几何关系检查。

### 7. 风控不是附属品，而是主线

默认风险参数：

- 单笔风险：`0.5%`
- 单标的最大仓位：`10%`
- 组合总风险暴露：`3%`
- ATR 止损倍数：`2.0`
- 最低盈亏比：`1.5R`

系统会根据入场区、止损距离和风险预算反推出建议仓位，而不是主观拍脑袋。

### 8. 每日简报已经重构为“晨会决策版”

日报不再堆一长串指标，而是先给结论，再给行动：

- `Executive Summary`
- `Market Filter`
- `Top Actions`
- `Watchlist`
- `Risk Actions`
- `Rejected Plans`
- `System Notes`

其中只有真正通过审批的 `BUY_TRIGGER / ADD_TRIGGER` 才会进入 `Top Actions`。  
`WATCH / WAIT / RISK_REDUCE / REJECT` 会分区展示，但不会伪装成可执行买入计划。

### 9. 提醒邮件和日报使用同一套语言

机会提醒只针对：

- `BUY_TRIGGER`
- `ADD_TRIGGER`

风险提醒只针对：

- `RISK_REDUCE`

提醒正文现在也采用“行动 + 理由 + 风险”的表达，不再是字段堆叠。

另外，提醒机制已经升级为：

- 相同 `symbol + alert_kind + signal_hash` 在 cooldown 内不重复发
- 如果 `signal_hash` 明显变化，允许在 cooldown 内重新提醒
- `RISK_REDUCE` 风险提醒为独立通道，可通过 `ENABLE_RISK_ALERTS` 单独开启

### 10. 决策有记忆，不再发完就忘

系统会把每日决策落盘到本地 memory log，记录：

- 日期
- symbol
- setup_type
- action
- rating
- score
- bull_case
- bear_case
- market_regime
- signal_hash
- trade plan summary
- rejection_reasons
- portfolio_decision

后续会尝试回填：

- 5 日收益
- 相对 `SPY` 的 alpha
- outcome 状态

这让系统开始具备“知道自己哪些 setup 更有效”的基础能力。

## 当前策略框架

你现在运行的是一套偏华尔街交易员思路的规则型波段系统，核心流程是：

1. 先看市场是否支持进攻  
2. 再给个股做多维评分  
3. 生成候选信号  
4. 做 action 一致性修正与计划校验  
5. 通过组合审批层决定今天真正批准哪些计划  
6. 用晨会式日报和提醒邮件输出最终决策

当前主要捕捉的机会仍然是两类：

- `突破入场`
- `趋势回踩加仓`

你没有引入自动下单，也没有让 LLM 接管买卖参数。核心执行逻辑依然是规则型、可复核、可测试的。

## 信号与动作

系统当前使用的动作集合：

- `BUY_TRIGGER`
- `ADD_TRIGGER`
- `WATCH`
- `WAIT`
- `RISK_REDUCE`
- `REJECT`

系统当前使用的评级集合：

- `Buy`
- `Overweight`
- `Hold`
- `Underweight`
- `No Trade`

评级表达态度，动作表达执行状态。两者同时存在，方便你快速判断“看法”和“操作”是否一致。

## 项目结构

```text
veyraquant/
  config.py            # 环境变量与配置
  data.py              # 行情、新闻、期权、缓存与降级
  indicators.py        # RSI、MACD、ATR、ADX 等指标
  market.py            # 市场环境过滤
  signals.py           # 信号评分、论证字段、交易计划
  risk.py              # 仓位与组合 heat 控制
  validator.py         # actionable 计划有效性校验
  decision_manager.py  # 组合审批层
  memory.py            # 决策记忆与 outcome 回填
  reporting.py         # 日报与提醒文案
  state.py             # 日报/提醒状态与冷却逻辑
  runner.py            # 主运行流程
  backtest.py          # 轻量回测
```

## 环境变量

### 邮件配置

```text
SMTP_USER
SMTP_APP_PASSWORD
FROM_EMAIL
TO_EMAIL
```

### 股票池与调度

```text
SYMBOLS=NVDA,TSLA,AAPL,AMD,MU,QQQ,SMH
MARKET_SYMBOLS=SPY,QQQ,SMH,^VIX
SEND_HOUR=7
SEND_MINUTE=30
SEND_WINDOW_MINUTES=30
ENABLE_ENTRY_ALERTS=true
ENABLE_RISK_ALERTS=false
ALERT_COOLDOWN_HOURS=12
ALERT_SCORE_THRESHOLD=65
INTRADAY_INTERVAL=30m
SUBJECT_PREFIX=VeyraQuant Quant Brief
DRY_RUN=false
FORCE_DAILY_REPORT=false
```

### 风控与计划校验

```text
ACCOUNT_EQUITY=
RISK_PER_TRADE_PCT=0.5
MAX_POSITION_PCT=10
PORTFOLIO_HEAT_MAX_PCT=3
ATR_STOP_MULTIPLIER=2.0
MIN_RR=1.5
MAX_ENTRY_ZONE_WIDTH_WARN_PCT=3.0
MAX_ENTRY_ZONE_WIDTH_REJECT_PCT=6.0
```

### 决策记忆

```text
MEMORY_LOG_PATH=memory/decision_log.jsonl
DECISION_MEMORY_HOLDING_DAYS=5
```

## 本地运行

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

本地 dry-run：

```powershell
$env:DRY_RUN="true"
python report.py
```

运行测试：

```powershell
python -m compileall report.py veyraquant tests
pytest
```

## GitHub Actions

项目内置定时 workflow，用于无人值守运行：

- 每 20 分钟自动运行
- 到达日报阈值后，当天任意一次成功运行都可补发日报
- 只在美股正常交易时段发送机会提醒
- 支持 `workflow_dispatch`
- 支持 `dry_run`
- 支持 `force_send=true` 的手动日报测试
- 只在状态文件变化时提交 `state/last_sent.json`

## 适合谁使用

VeyraQuant 适合：

- 想系统化跟踪美股波段机会的交易者
- 想把主观盯盘流程变成可重复决策流程的人
- 想明确入场、止损、目标位和仓位的人
- 想用免费数据源构建轻量量化辅助系统的人
- 想学习如何把交易逻辑拆成数据、信号、风控、审批、报告五层的人

## 不适合谁使用

VeyraQuant 不适合：

- 想要自动下单机器人
- 想做高频或毫秒级交易
- 想要“稳赚策略”或收益承诺
- 不愿意人工复核交易计划的人

## 免责声明

VeyraQuant 仅用于信息分析与交易辅助，不构成投资建议，也不代表任何自动交易指令。所有交易计划都需要人工复核，任何投资决策与风险均由使用者自行承担。
