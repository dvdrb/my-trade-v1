# How to Use

This project is a local-first Python trading bot foundation for the Trend-Aligned Triangle Breakout strategy.

It can:

- load safe YAML configuration
- store candles, signals, and trades in SQLite
- import candle CSV files
- fetch read-only Hyperliquid candle data
- evaluate deterministic strategy signals
- run local backtests
- run local paper trading

It does not place real orders. Live execution is not implemented.

## Requirements

- Python 3.12+
- Local terminal access from the project root

Install dependencies:

```bash
python -m pip install -e ".[dev]"
```

## Configuration

Default strategy settings are in:

```text
app/config/strategy.yaml
```

The default mode is safe:

```yaml
mode: paper
paper:
  enabled: true
```

Create a local `.env` file if needed:

```bash
cp .env.example .env
```

Do not commit real secrets.

## Initialize the Database

Create the SQLite database and tables:

```bash
python scripts/init_db.py
```

Default database path:

```text
data/bot.sqlite3
```

## Import Candles from CSV

CSV files should include at least:

```text
open_time,open,high,low,close
```

Optional columns:

```text
symbol,timeframe,close_time,volume
```

Import candles:

```bash
python scripts/import_candles_csv.py data/sample_candles.csv --symbol BTC --timeframe 1h
```

Replace `data/sample_candles.csv` with the path to your own CSV file when importing real data.

Duplicate candles are ignored using the unique key:

```text
symbol, timeframe, open_time
```

## Fetch Hyperliquid Candles

Fetch read-only candle data from Hyperliquid and save it locally:

```bash
python scripts/fetch_candles.py --symbol BTC --timeframe 1h --limit 5000
```

Supported intervals currently include:

```text
1m, 5m, 15m, 1h, 4h, 1d
```

## Run a Backtest

Backtests replay stored candles sequentially and call the same strategy evaluator used by paper mode:

```bash
python scripts/run_backtest.py --symbol BTC --timeframe 1h
```

Reports are written to:

```text
reports/backtests/<run_id>/
```

Generated files:

```text
summary.json
trades.csv
signals.csv
equity_curve.csv
```

## Run Local Paper Trading

Paper mode fetches candles on a polling loop, evaluates new closed candles, stores signals, and simulates trades locally.

```bash
python scripts/run_paper.py --symbol BTC --timeframe 1h --poll-seconds 60
```

Paper mode does not place real orders.

## Run Tests

```bash
python -m pytest
```

## Safety Notes

- Real order execution is not implemented.
- No live trading mode exists yet.
- No Hyperliquid account trading calls are made.
- Secrets should only be provided through `.env` or environment variables.
- If strategy evaluation is uncertain, signals should be rejected with clear reasons.
