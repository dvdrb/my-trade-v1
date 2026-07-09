# AGENTS.md

## Project

This is a simple local-first Python trading bot for Hyperliquid.

The bot detects triangle breakout setups from candle data, validates them with trend and support/resistance zones, backtests the strategy, and can run local paper trading.

This is not a SaaS platform, dashboard, multi-user system, or cloud service.

## Main Goal

Build a local bot that can:

1. Store historical candles locally.
2. Detect pivots, trend, support/resistance zones, and triangle patterns.
3. Generate accepted/rejected trade signals with clear reasons.
4. Backtest the same strategy logic used in paper mode.
5. Run local paper trading.
6. Fetch candle data from Hyperliquid.
7. Add live execution only later, when explicitly requested.

## Simplicity Rules

Keep the project simple and maintainable.

Prefer:

- Clear Python modules
- Small functions
- Dataclasses or simple Pydantic models
- SQLite
- YAML config
- CLI scripts
- Plain logs
- Direct tests

Avoid:

- Unused abstractions
- Complex class hierarchies
- Plugin systems
- Event buses
- Queues
- Microservices
- Web dashboards
- Async complexity unless clearly needed
- Multi-user logic
- Multi-exchange logic
- Cloud/deployment logic
- Features not required by the current task

Build only what is needed for one local user running one bot.

## Safety Rules

- Do not implement live order placement unless the task explicitly asks for it.
- Do not place real orders in tests.
- Do not enable live trading by default.
- Do not enable mainnet execution by default.
- Never log secrets, private keys, wallet keys, API keys, seed phrases, or tokens.
- Do not hardcode secrets.
- Use `.env` or environment variables for secrets.
- The bot must fail closed. If something is uncertain, reject the trade and log the reason.

## Architecture Rules

Strategy logic must stay independent from exchange, database, and runtime code.

Allowed dependency direction:

```text
scripts -> app modules
runtime -> strategy
runtime -> data
backtest -> strategy
backtest -> data
strategy -> indicators
strategy -> core
exchange -> core
data -> core
```

Not allowed:

```text
strategy -> exchange
strategy -> database
strategy -> runtime
strategy -> alerts
```

Use this simple structure unless the task clearly requires otherwise:

```text
app/
  config/
  core/
  data/
  exchange/
  indicators/
  strategy/
  backtest/
  runtime/

scripts/
tests/
data/
logs/
reports/
```

## Strategy Rules

Strategy name:

```text
Trend-Aligned Triangle Breakout
```

Signal model:

```text
Triangle setup
+ trend alignment
+ support/resistance context
+ breakout confirmation
+ risk/reward validation
= trade signal
```

Supported triangle types:

- Ascending triangle
- Descending triangle
- Symmetrical triangle

Every strategy evaluation should return one of:

```text
no_setup
rejected
accepted
```

Rejected signals must include clear reasons.

Accepted signals must include:

- symbol
- timeframe
- side
- score
- reasons
- entry price
- stop loss
- take profit
- reward/risk
- strategy version

Hard risk gates must override score. A high score must never allow an invalid trade.

## Backtesting Rules

- Avoid lookahead bias.
- Replay candles sequentially.
- Use only data available at that simulated time.
- Use the same strategy evaluator as paper mode.
- Apply fees and slippage.
- Enter trades only after signal confirmation.
- Handle ambiguous candles conservatively when both stop loss and take profit are touched.
- Export trades, signals, rejections, and summary metrics.

Required metrics:

- total trades
- win rate
- average R
- expectancy
- profit factor
- max drawdown
- max losing streak
- rejection reason counts
- performance by side
- performance by triangle type

## Default Local Safety

Default configuration must be safe:

```text
mode: paper
paper.enabled: true
live trading disabled
no order execution
```

Do not add live execution config until the task explicitly asks for live execution.

## Coding Standards

- Python 3.12+
- Type hints required
- Prefer dataclasses or Pydantic models
- Prefer pure functions for strategy logic
- Keep files small and readable
- Avoid unrelated refactors
- Add tests for important logic
- Run `pytest` before finishing when possible

## Before Finishing Any Task

Return:

1. What changed
2. Tests added or updated
3. Tests run
4. Any limitations or follow-up needed
