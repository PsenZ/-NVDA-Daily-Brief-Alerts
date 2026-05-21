# VeyraQuant

VeyraQuant is a semi-automated swing-trading research assistant for a small US equity watchlist. It creates a daily decision brief and optional intraday alerts, but it does not place orders or connect to a broker.

The system is designed for 5-20 symbols, free data sources first, and human-confirmed execution. It focuses on clear trade plans, portfolio-level filtering, risk controls, and post-decision review.

## What It Does

- Monitors a configurable watchlist, defaulting to `NVDA,TSLA,AAPL,AMD,MU,QQQ,SMH`.
- Uses market filters from `SPY`, `QQQ`, `SMH`, and `^VIX`.
- Scores each symbol across trend, momentum, relative strength, volume, volatility/options, sentiment, events, and market regime.
- Classifies each result into `BUY_TRIGGER`, `ADD_TRIGGER`, `WATCH`, `WAIT`, `RISK_REDUCE`, or `REJECT`.
- Builds actionable trade plans only for final `BUY_TRIGGER` and `ADD_TRIGGER` signals.
- Validates entry zone, stop, targets, RR, position size, and max loss before allowing a buy/add plan into the report.
- Applies portfolio heat controls and a portfolio manager approval layer before presenting top actions.
- Sends a daily morning brief and optional opportunity/risk alerts by email.
- Keeps a decision log and can summarize which setups have recently worked.

## Strategy Logic

VeyraQuant is not a black-box predictor. It is a rules-based decision engine built around structured evidence:

- `bull_case`: why the setup could work now.
- `bear_case`: what can invalidate or weaken the setup.
- `rating`: `Buy`, `Overweight`, `Hold`, `Underweight`, or `No Trade`.
- `action`: the execution state, such as `BUY_TRIGGER` or `RISK_REDUCE`.
- `conviction_level`: high, medium, or low.
- `decision_balance`: favorable, mixed, fragile, defensive, or blocked.

The current setup families are:

- `breakout_entry`: trend alignment plus breakout confirmation, volume support, and anti-chase discipline.
- `pullback_add`: trend intact, controlled pullback, lighter volume, and RSI in a healthy reset zone.
- `risk_reduce`: low score or overheating/weakening conditions that should reduce risk attention.

Core thresholds are parameterized in `strategies/default.json`, with defaults matching the existing strategy behavior.

## Portfolio Manager

After symbols are scored, the portfolio layer decides what is actually worth acting on today.

It keeps:

- `approved`: best actionable ideas for today.
- `deferred`: good candidates delayed by capacity, sector concentration, or quality.
- `watchlist`: names that need better confirmation.
- `risk_action`: risk-reduction signals.
- `rejected`: invalid or vetoed plans.

It also records:

- `approval_rank_score`
- `sector_bucket`
- `approval_reason_code`
- `defer_reason_code`
- `portfolio_notes`

The portfolio layer now guards both sector risk and sector position exposure. If a new approved idea would push a sector beyond its configured risk or position budget, the lower-ranked candidate is deferred rather than presented as a fresh top action.

Default sector controls:

```text
SECTOR_RISK_LIMITS_JSON={"semiconductor":1.2,"mega_growth":1.5,"auto_growth":0.8,"general":1.0}
SECTOR_POSITION_LIMITS_JSON={"semiconductor":20,"mega_growth":25,"auto_growth":10,"general":10}
MAX_APPROVED_ACTIONS_RISK_ON=3
MAX_APPROVED_ACTIONS_NEUTRAL=2
MAX_APPROVED_ACTIONS_RISK_OFF=0
```

This keeps the daily report from becoming a pile of good-looking but correlated signals.

## Position Context

Risk signals can now be evaluated against a local position file.

Default path:

```text
state/positions.json
```

Example:

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

## Decision Review

The decision log is stored at:

```text
memory/decision_log.jsonl
```

VeyraQuant can aggregate historical outcomes by:

- `setup_type`
- `action`
- `rating`
- `market_regime`
- `portfolio_decision`

Metrics include count, resolved/unresolved count, average 5-day return, average alpha versus SPY, and win rate.

Run locally:

```powershell
python -m veyraquant.memory_review
```

The daily report includes only a short review note, not a full table.

## Email Output

Emails are sent as `multipart/alternative`:

- `text/plain` remains the official fallback.
- `text/html` adds a more readable morning-brief layout.

Daily brief sections:

- Executive Summary
- Market Filter
- Top Actions
- Deferred Ideas
- Watch / Wait
- Risk Actions
- Rejected Plans
- System Notes

Opportunity alerts and risk alerts use the same action-plus-reason language as the daily brief.

## Configuration

Required email secrets:

```text
SMTP_USER
SMTP_APP_PASSWORD
FROM_EMAIL
TO_EMAIL
```

Core runtime settings:

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
```

Context and memory:

```text
POSITIONS_PATH=state/positions.json
STRATEGY_CONFIG_PATH=strategies/default.json
MEMORY_LOG_PATH=memory/decision_log.jsonl
DECISION_MEMORY_HOLDING_DAYS=5
```

## Run Locally

Install dependencies:

```powershell
python -m pip install -r requirements.txt
```

Dry run:

```powershell
$env:DRY_RUN="true"
python report.py
```

Run tests:

```powershell
python -m compileall report.py veyraquant tests
pytest
```

## GitHub Actions

The workflow can run automatically on schedule or manually through `workflow_dispatch`.

Recommended secrets:

- `SMTP_USER`
- `SMTP_APP_PASSWORD`
- `FROM_EMAIL`
- `TO_EMAIL`
- `POSITIONS_JSON` optional private positions JSON. If present, the workflow writes it to `state/positions.json` only for that run.

Recommended variables:

- `SYMBOLS`
- `ENABLE_ENTRY_ALERTS`
- `ENABLE_RISK_ALERTS`
- `SEND_HOUR`
- `SEND_MINUTE`
- `SEND_WINDOW_MINUTES`

For a manual test, use the workflow input `force_send=true` and `dry_run=false`.

Private holdings should not be committed. Put the full JSON payload in the repository secret `POSITIONS_JSON` instead:

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

## Safety Notes

- No broker API.
- No automatic order placement.
- No account credentials or private holdings are saved in the repo.
- Account size and private positions, if used, should be injected through GitHub Secrets.
- Every trade plan is decision support only and requires human review.

