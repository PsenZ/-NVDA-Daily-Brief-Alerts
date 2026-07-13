# VeyraQuant

## English

VeyraQuant is a semi-automated swing-trading research assistant for a focused US equity watchlist. It generates daily decision briefs and optional opportunity/risk alerts on US market weekdays, but it does not place orders, connect to a broker, or store brokerage credentials.

It is built for 5-20 symbols, free data sources first, and human-confirmed execution. The system emphasizes evidence, risk controls, portfolio approval, position context, and post-decision review.

## 中文

VeyraQuant 是一个面向美股小型股票池的半自动波段交易研究助手。它会生成每日交易决策简报，并在美股工作日全天候检查可选机会/风险提醒，但不会自动下单，不连接券商 API，也不会保存券商账户凭证。

系统适合 5-20 个标的，优先使用免费数据源，所有交易计划都需要人工确认。核心重点是：证据、风控、组合审批、持仓上下文和决策复盘。

## What It Does / 系统功能

- Monitors a configurable watchlist, defaulting to `NVDA,TSLA,AAPL,AMD,MU,QQQ,SMH`.
- 默认监控可配置股票池：`NVDA,TSLA,AAPL,AMD,MU,QQQ,SMH`。
- Uses market filters from `SPY`, `QQQ`, `SMH`, and `^VIX`.
- 使用 `SPY`、`QQQ`、`SMH`、`^VIX` 作为大盘、科技、半导体和波动率过滤器。
- Scores each symbol across trend, momentum, relative strength, volume, volatility/options, sentiment, events, and market regime.
- 从趋势、动量、相对强弱、成交量、波动率/期权、情绪、事件风险和市场环境多个维度评分。
- Classifies each result into `BUY_TRIGGER`, `ADD_TRIGGER`, `WATCH`, `WAIT`, `RISK_REDUCE`, or `REJECT`.
- 将每个标的归类为 `BUY_TRIGGER`、`ADD_TRIGGER`、`WATCH`、`WAIT`、`RISK_REDUCE` 或 `REJECT`。
- Builds actionable trade plans only for final `BUY_TRIGGER` and `ADD_TRIGGER` signals.
- 只有最终确认为 `BUY_TRIGGER` 或 `ADD_TRIGGER` 的信号才会生成可执行交易计划。
- Validates entry zone, stop, targets, RR, position size, and max loss before allowing a buy/add plan into the report.
- 在交易计划进入日报前，会校验入场区、止损、目标位、盈亏比、仓位比例和最大亏损。
- Applies portfolio heat controls and a portfolio manager approval layer before presenting top actions.
- 在展示 Top Actions 前，会经过组合 heat 控制和 Portfolio Manager 审批。
- Sends a daily morning brief and optional opportunity/risk alerts by email.
- 通过邮件发送每日晨会简报，也可发送机会提醒和风险提醒。
- Keeps a decision log and can summarize which setups have recently worked.
- 保存决策日志，并可复盘哪些 setup 最近表现更好。
- Applies a data quality gate so stale daily price cache cannot generate actionable buy/add plans.
- 使用数据质量门禁，旧的日线缓存不能生成可执行买入/加仓计划。

## Strategy Logic / 策略逻辑

VeyraQuant is not a black-box predictor. It is a rules-based decision engine built around structured evidence.

VeyraQuant 不是黑箱预测模型，而是基于规则和结构化证据的交易决策引擎。

Key fields:

关键字段：

- `bull_case`: why the setup could work now.  
  多头依据：为什么这个 setup 现在可能有效。
- `bear_case`: what can invalidate or weaken the setup.  
  空头/反方依据：什么因素可能使 setup 失效或变弱。
- `rating`: `Buy`, `Overweight`, `Hold`, `Underweight`, or `No Trade`.  
  评级：`Buy`、`Overweight`、`Hold`、`Underweight`、`No Trade`。
- `action`: execution state, such as `BUY_TRIGGER` or `RISK_REDUCE`.  
  动作：执行状态，例如 `BUY_TRIGGER` 或 `RISK_REDUCE`。
- `conviction_level`: high, medium, or low.  
  置信度：high、medium、low。
- `decision_balance`: favorable, mixed, fragile, defensive, or blocked.  
  决策平衡：favorable、mixed、fragile、defensive、blocked。

Current setup families:

当前 setup 类型：

- `breakout_entry`: trend alignment, breakout confirmation, volume support, and anti-chase discipline.  
  突破入场：趋势排列、突破确认、成交量支持和防追高纪律。
- `pullback_add`: trend intact, controlled pullback, lighter volume, and RSI in a healthy reset zone.  
  趋势回踩加仓：趋势未破、回踩有序、缩量回撤、RSI 处于健康重置区间。
- `risk_reduce`: low score or overheating/weakening conditions that should reduce risk attention.  
  风险降低：低分、过热或趋势变弱时，提示降低风险关注。

Core thresholds are parameterized in `strategies/default.json`, with defaults matching the existing strategy behavior.

核心阈值已外置到 `strategies/default.json`，默认参数保持当前策略行为不变。

## Portfolio Manager / 组合审批

After symbols are scored, the portfolio layer decides what is actually worth acting on today.

单标的评分完成后，组合层会判断今天哪些机会真正值得执行。

It keeps:

系统会维护：

- `approved`: best actionable ideas for today.  
  今日批准执行的最佳机会。
- `deferred`: good candidates delayed by capacity, sector concentration, or quality.  
  因容量、行业集中度或质量问题被延后的候选机会。
- `watchlist`: names that need better confirmation.  
  需要继续观察、等待更好确认的标的。
- `risk_action`: risk-reduction signals.  
  风险控制信号。
- `rejected`: invalid or vetoed plans.  
  无效或被否决的计划。

It also records:

同时记录：

- `approval_rank_score`
- `sector_bucket`
- `approval_reason_code`
- `defer_reason_code`
- `portfolio_notes`

The Portfolio Risk Guard controls both sector risk and sector position exposure. If approving a new idea would push a sector beyond its configured risk or position budget, the lower-ranked candidate is deferred instead of being shown as a fresh top action.

Portfolio Risk Guard 会同时控制行业风险预算和行业仓位暴露。如果批准一个新机会会导致某个行业超过风险预算或仓位预算，排名较低的候选会进入 deferred，而不是被当成新的 Top Action 展示。

Default sector controls:

默认行业控制参数：

```text
SECTOR_RISK_LIMITS_JSON={"semiconductor":1.2,"mega_growth":1.5,"auto_growth":0.8,"general":1.0}
SECTOR_POSITION_LIMITS_JSON={"semiconductor":20,"mega_growth":25,"auto_growth":10,"general":10}
MAX_APPROVED_ACTIONS_RISK_ON=3
MAX_APPROVED_ACTIONS_NEUTRAL=2
MAX_APPROVED_ACTIONS_RISK_OFF=0
```

This prevents the daily brief from presenting several correlated trades as if they were independent opportunities.

这可以避免日报把多个高度相关的交易机会误展示成彼此独立的机会。

## Data Quality Gate / 数据质量门禁

Each symbol carries `DataQuality` metadata:

每个标的都会携带 `DataQuality` 元数据：

- `price_freshness`
- `intraday_freshness`
- `fundamentals_freshness`
- `options_available`
- `news_available`
- `cache_age_hours`
- `data_quality_level`: `HIGH`, `MEDIUM`, or `LOW`

Daily price data is the hard gate. If live data is unavailable and the daily cache is stale, the system will downgrade actionable signals to `WAIT` rather than allowing `BUY_TRIGGER` or `ADD_TRIGGER`.

日线价格数据是硬门禁。如果实时数据不可用且日线缓存过旧，系统会把可执行信号降级为 `WAIT`，而不是允许 `BUY_TRIGGER` 或 `ADD_TRIGGER`。

Intraday data is softer. If intraday data is missing, the symbol can still appear in the daily report, but entry alerts are disabled for that result.

盘中数据是软门禁。如果盘中数据缺失，标的仍可出现在日报中，但不会触发入场提醒。

Default freshness controls:

默认新鲜度控制：

```text
PRICE_CACHE_ACTIONABLE_MAX_AGE_HOURS=24
PRICE_CACHE_INVALID_MAX_AGE_HOURS=72
```

## Structured Trade Plan / 结构化交易计划

Trade plans keep human-readable display fields and numeric validation fields separate.

交易计划现在同时保留给人看的展示字段，以及给系统校验用的数字字段。

Display fields:

展示字段：

- `entry_zone`
- `stop`
- `targets`

Numeric fields:

数字字段：

- `entry_low`
- `entry_high`
- `stop_price`
- `target1`
- `target2`

The validator now uses numeric fields first and only falls back to parsing display strings for backward compatibility. This keeps email formatting changes from accidentally changing risk validation.

校验器会优先使用数字字段，只在兼容旧调用时才回退解析展示字符串。这样即使邮件展示格式调整，也不会影响风控校验逻辑。

## Position Context / 持仓上下文

Risk signals can be evaluated against a local private position file.

风险信号可以结合本地私密持仓文件进行判断。

Default path:

默认路径：

```text
state/positions.json
```

Example:

示例：

```json
{
  "positions": [
    {
      "symbol": "NVDA",
      "position_pct": 7.5,
      "cost_basis": 900.25,
      "opened_at": "2026-04-01",
      "notes": "Core AI position"
    }
  ]
}
```

If a `RISK_REDUCE` signal matches an open position, the report marks it as an open-position risk action and suggests `trim` or `de-risk`. If no position is recorded, it becomes `monitor-only` instead of implying an immediate sell.

如果 `RISK_REDUCE` 命中真实持仓，日报会标记为针对已有持仓的风险动作，并建议 `trim` 或 `de-risk`。如果没有记录持仓，则显示为 `monitor-only`，不会误导成“立即减仓”。

## Decision Review / 决策复盘

The decision log is stored at:

决策日志保存位置：

```text
memory/decision_log.jsonl
```

VeyraQuant can aggregate historical outcomes by:

VeyraQuant 可以按以下维度聚合历史结果：

- `setup_type`
- `action`
- `rating`
- `market_regime`
- `portfolio_decision`

Metrics include count, resolved/unresolved count, average 5-day return, average alpha versus SPY, and win rate.

指标包括样本数、已解析/未解析数量、平均 5 日收益、相对 SPY 的平均 alpha 和胜率。

Run locally:

本地运行：

```powershell
python -m veyraquant.memory_review
```

The daily report includes only a short review note, not a full table.

日报只展示简短复盘摘要，不会塞入完整统计表。

## Email Output / 邮件输出

Emails are sent as `multipart/alternative`:

邮件使用 `multipart/alternative` 格式发送：

- `text/plain` remains the official fallback.  
  `text/plain` 保留为正式 fallback。
- `text/html` adds a more readable morning-brief layout.  
  `text/html` 提供更易读的晨会简报排版。

Daily brief sections:

日报结构：

- Executive Summary / 执行摘要
- Market Filter / 市场过滤器
- Top Actions / 今日重点行动
- Deferred Ideas / 延后机会
- Watch / Wait / 观察与等待
- Risk Actions / 风险动作
- Rejected Plans / 被拒绝计划
- System Notes / 系统备注

Opportunity alerts and risk alerts use the same action-plus-reason language as the daily brief.

机会提醒和风险提醒使用与日报一致的“行动 + 理由”语言。

Alert timing:

提醒时间：

- GitHub Actions runs every 20 minutes.
- GitHub Actions 每 20 分钟运行一次。
- Daily reports follow the configured Sydney-time send window.
- 日报按照配置的悉尼时间发送窗口执行。
- Opportunity and risk alerts are checked all day on US market weekdays, not only during regular US trading hours.
- 机会提醒和风险提醒会在美股工作日全天候检查，不再限制为美股常规交易时段。
- Alerts are skipped on US market weekends.
- 美股周末不开盘时不发送提醒。

## Configuration / 配置

Required email secrets:

必需邮件 Secrets：

```text
SMTP_USER
SMTP_APP_PASSWORD
FROM_EMAIL
TO_EMAIL
```

Core runtime settings:

核心运行配置：

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

Risk settings:

风控配置：

```text
ACCOUNT_EQUITY=
RISK_PER_TRADE_PCT=0.5
MAX_POSITION_PCT=10
PORTFOLIO_HEAT_MAX_PCT=3
ATR_STOP_MULTIPLIER=2.0
MIN_RR=1.5
MAX_ENTRY_ZONE_WIDTH_WARN_PCT=3.0
MAX_ENTRY_ZONE_WIDTH_REJECT_PCT=6.0
SECTOR_MAP_JSON={"NVDA":"semiconductor","AMD":"semiconductor","MU":"semiconductor","SMH":"semiconductor","QQQ":"mega_growth","AAPL":"mega_growth","MSFT":"mega_growth","TSLA":"auto_growth"}
SECTOR_RISK_LIMITS_JSON={"semiconductor":1.2,"mega_growth":1.5,"auto_growth":0.8,"general":1.0}
SECTOR_POSITION_LIMITS_JSON={"semiconductor":20,"mega_growth":25,"auto_growth":10,"general":10}
MAX_APPROVED_ACTIONS_RISK_ON=3
MAX_APPROVED_ACTIONS_NEUTRAL=2
MAX_APPROVED_ACTIONS_RISK_OFF=0
PRICE_CACHE_ACTIONABLE_MAX_AGE_HOURS=24
PRICE_CACHE_INVALID_MAX_AGE_HOURS=72
```

Context and memory:

上下文与复盘：

```text
POSITIONS_PATH=state/positions.json
STRATEGY_CONFIG_PATH=strategies/default.json
MEMORY_LOG_PATH=memory/decision_log.jsonl
DECISION_MEMORY_HOLDING_DAYS=5
```

## Run Locally / 本地运行

Install dependencies:

安装依赖：

```powershell
python -m pip install -r requirements.txt
```

Dry run:

本地 dry run：

```powershell
$env:DRY_RUN="true"
python report.py
```

Run tests:

运行测试：

```powershell
python -m compileall report.py veyraquant tests
pytest
```

## GitHub Actions

The workflow can run automatically on schedule or manually through `workflow_dispatch`.

GitHub Actions 可以定时自动运行，也可以通过 `workflow_dispatch` 手动运行。

Recommended secrets:

推荐配置的 Secrets：

- `SMTP_USER`
- `SMTP_APP_PASSWORD`
- `FROM_EMAIL`
- `TO_EMAIL`
- `POSITIONS_JSON`: optional private positions JSON. If present, the workflow writes it to `state/positions.json` only for that run.  
  可选私密持仓 JSON。如果配置了它，workflow 只会在当次运行中临时写入 `state/positions.json`。

Recommended variables:

推荐配置的变量：

- `SYMBOLS`
- `ENABLE_ENTRY_ALERTS`
- `ENABLE_RISK_ALERTS`
- `SEND_HOUR`
- `SEND_MINUTE`
- `SEND_WINDOW_MINUTES`

For a manual test, use:

手动测试建议：

```text
force_send=true
dry_run=false
```

Private holdings should not be committed. Put the full JSON payload in the repository secret `POSITIONS_JSON` instead.

私密持仓不要提交到仓库。请把完整 JSON 放进 GitHub repository secret：`POSITIONS_JSON`。

Example:

示例：

```json
{
  "positions": [
    {
      "symbol": "NVDA",
      "position_pct": 7.5,
      "cost_basis": 900.25,
      "opened_at": "2026-04-01",
      "notes": "Optional private note"
    }
  ]
}
```

The workflow validates this secret as JSON, writes it locally during the run, and does not commit it back to the repository.

workflow 会校验这个 Secret 是否为合法 JSON，在运行时临时写入本地文件，并且不会把它提交回仓库。

## Safety Notes / 安全说明

- No broker API.  
  不接券商 API。
- No automatic order placement.  
  不自动下单。
- No account credentials or private holdings are saved in the repo.  
  仓库不保存账户凭证或真实私密持仓。
- Account size and private positions, if used, should be injected through GitHub Secrets.  
  账户规模和私密持仓如需使用，应通过 GitHub Secrets 注入。
- Every trade plan is decision support only and requires human review.  
  所有交易计划仅供辅助决策，最终执行必须由人工确认。

## Important Disclaimer / 重要免责声明

This is a rules-based research assistant, not a statistically validated alpha model. Reports, alerts, backtests, and decision-review outputs are diagnostic tools and should not be treated as proof of future performance.

本项目是规则型研究助手，不是经过统计验证的 alpha 模型。日报、提醒、回测和决策复盘都属于诊断工具，不应被视为未来收益的证明。

## Dashboard & Operations / 仪表盘与运维

- **Dashboard / 仪表盘**: static site under `docs/`, fed by `docs/data/*.json` exported after every real nightly send. Enable GitHub Pages: Settings → Pages → Deploy from a branch → `main` + `/docs`. URL: `https://<owner>.github.io/veyraquant/`. The committed seed data (marked "sample") renders until the first real export overwrites it.
- **仪表盘**：`docs/` 下的纯静态站点，读取每次夜间真实发送后导出的 `docs/data/*.json`。开启方式：Settings → Pages → Deploy from a branch → `main` + `/docs`。首次真实导出前显示"样例数据"。
- **Watchlist via Variables / 用 Variables 配股票池**: set repository Variables (Settings → Secrets and variables → Actions → Variables): `SYMBOLS`, `MARKET_SYMBOLS`, optional `SECTOR_MAP_JSON` / `SECTOR_RISK_LIMITS_JSON` / `SECTOR_POSITION_LIMITS_JSON`. Unset variables fall back to the defaults in `daily.yml` — no YAML edit needed to change the watchlist.
- **Workflows / 调度**: `daily.yml` runs the full pipeline nightly after the US close (brief email + armed plans + dashboard export); `premarket.yml` emails a readiness digest ~30-60 min before the open (distance from each armed plan to its trigger, measured from the last completed daily close — never extended-hours quotes, never fires a trigger); `intraday.yml` checks frozen plan levels every 5 minutes during US regular hours and alerts once per plan on trigger/invalidation; `ci.yml` runs pytest + compileall on every push/PR.
- **盘前预备清单 / Pre-market digest**: `premarket.yml` 在开盘前发一封"预备清单"邮件——每个冻结计划距触发价多远(基于**上一根完成日线收盘**,不用不可靠的盘前报价,不做触发判定)。`PREMARKET_BRIEFING_ENABLED=false` 可关闭。盘中触发已从 10 分钟提速到 **5 分钟**。
- **Research CLIs / 研究工具**: `python -m veyraquant.memory_review` (decision-log statistics with t-stats and horizon comparison), `python walkforward.py` (out-of-sample threshold evaluation, net of costs).

---

## Capabilities, Boundaries & Operating Guide / 能力、边界与操作指南

> This section is the authoritative summary of what the system on `main` actually does. It reflects the merged pipeline (E0–R8/R7), not any single feature branch. 本节是 `main` 当前真实行为的权威总结。

### What it is / 定位

A **rules-based, semi-automated US-equity swing-trading research assistant**. It produces a daily decision brief by email and optional intraday opportunity/risk alerts. It is decision support: **it never places orders, connects to a broker, or stores brokerage credentials.**

规则型、半自动的美股波段交易研究助手。生成每日邮件简报和可选盘中提醒。**不下单、不连券商、不存券商凭证。**

### Hard boundaries / 硬性边界

- **Not a validated alpha model.** Scoring weights are hand-set hypotheses. There is no out-of-sample proof of edge yet; the walk-forward tooling exists to *test* that claim once enough resolved decisions accumulate. Treat it as a discipline tool, not a predictor. 评分权重是人工假设，尚无样本外 edge 证据；把它当纪律工具，不是预测器。
- **Daily-timeframe by design.** Free yfinance + RSS data supports daily decisions, not minute-level trading. The two-tier architecture (nightly frozen plans + intraday level triggers) reflects this. 免费数据只支撑日线级；两级架构（夜间冻结计划 + 盘中电平触发）正是这个定位的产物。
- **US market only.** The instrument registry classifies US tickers (stock/ETF/index/crypto) with leveraged/inverse/ADR flags, liquidity and history gates. Non-US symbols are out of scope. 仅美股。
- **5-day holding, 2×ATR stop.** An earnings gap can wipe out several normal trades — hence the earnings-blackout veto. 持有 5 天、止损 2×ATR；财报静默期否决保护跳空风险。
- **Every trade plan requires human review.** No automatic execution. 所有计划需人工复核。

### Two-tier signal flow / 两级信号

1. **Nightly (after US close)** — full pipeline on *completed* daily bars: score → classify → veto gates → trade plan + validation → portfolio approval (heat cap, sector budgets, approval caps, correlation-aware sizing) → email + freeze approved plans to `state/armed_plans.json` + export dashboard JSON + write `docs/data/health.json`. 夜间用完成日线跑全管线，冻结批准计划、导出数据、写健康清单。
2. **Intraday (US regular hours, every 10 min)** — checks frozen plan price levels only, never re-scores: price enters the frozen entry zone → TRIGGER; hits the frozen stop → INVALIDATED; each plan alerts once. 盘中只对冻结计划做电平检测，不重算评分，一次性告警。

### Veto gates (machine-readable reason codes) / 否决门

`market_risk_off`, `negative_news_veto`, `earnings_blackout`, `leveraged_product_policy`, `insufficient_liquidity`, `rr_below_min`, `trade_plan_validation_failed`, `data_quality_gate`, `insufficient_daily_data`. Every rejection carries a code and an evidence item.

### Risk framework (seven layers) / 七层风控

fixed-fraction risk per trade (0.5%) → ATR stop → RR floor (1.5) → per-symbol position cap (10%) → global portfolio heat cap (3%, allocated *after* approval with proportional haircut) → sector risk/position budgets → market-regime approval caps (risk-on 3 / neutral 2 / risk-off 0). Highly correlated approved names are additionally size-halved (R7).

### Deploy / 部署

1. Fork the repo; enable Actions.
2. **Secrets** (Settings → Secrets and variables → Actions → Secrets): `SMTP_USER`, `SMTP_APP_PASSWORD`, `FROM_EMAIL`, `TO_EMAIL`; optional `POSITIONS_JSON` (private holdings, never committed).
3. **Variables** (optional watchlist override): `SYMBOLS`, `MARKET_SYMBOLS`, `SECTOR_MAP_JSON`, …
4. **GitHub Pages** for the dashboard: Settings → Pages → Deploy from a branch → `main` + `/docs`.
5. Workflows run themselves: `daily.yml` (nightly full run), `intraday.yml` (RTH triggers), `ci.yml` (tests on push/PR).

### Local use / 本地使用

```bash
python -m venv .venv && source .venv/Scripts/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest                                          # must be all green (201 tests)
DRY_RUN=true FORCE_DAILY_REPORT=true SYMBOLS=NVDA python report.py   # dry run, no email/state
```

### Research & health CLIs / 研究与健康工具

- `python -m veyraquant.memory_review` — decision-log statistics: per-bucket alpha with t-stats, 95% CI, significance gate, score bands, holding-horizon comparison. Meaningful only after ~30 resolved decisions accumulate. 决策日志统计，需积累约 30 条已回填决策才有意义。
- `python walkforward.py` — walk-forward threshold tuning on the event-driven engine with cost model and failure-attribution (setup / regime / sector / data-quality cuts); refuses to claim edge under 30 validation trades. 事件引擎 walk-forward + 失败归因；不足 30 笔不下结论。
- `docs/data/health.json` + dashboard System Health card — last run time/duration, symbols live/cache/failed, email/export status, intraday heartbeat. 运行健康清单与仪表盘健康卡。

### Honesty about effectiveness / 关于有效性的诚实说明

As a **decision-support and risk-discipline system**: effective and mature. As a **money-making alpha system**: unproven, and provable only after months of real running that fill the decision log, then reading the review/walk-forward CLIs above. Until then, use the discipline, not the predictions.

作为**决策支持 + 风控纪律系统**：成熟有效。作为**能盈利的 alpha 系统**：未经证明，且只有在系统真实运行数月、决策日志积累后、通过上述复盘工具才能验证。在那之前，用它的纪律，别信它的预测。
