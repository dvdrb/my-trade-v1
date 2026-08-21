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

## Verified Historical Research Import

The public Hyperliquid candle endpoint retains only 5,000 recent candles, so
it cannot provide the research dataset by itself. Use a verified canonical
15-minute CSV containing the exact same continuous UTC grid for `BTC`, `ETH`,
and `SOL`. Required columns are:

```text
symbol,open_time,close_time,open,high,low,close,volume
```

Timestamps are Unix milliseconds. Verify the file's trusted digest, then run:

```bash
shasum -a 256 /path/to/hyperliquid_15m.csv
python scripts/import_hyperliquid_history.py /path/to/hyperliquid_15m.csv \
  --sha256 <trusted-sha256>
python scripts/audit_research_data.py
```

The importer refuses data with gaps, duplicates, invalid OHLC values, unequal
symbol grids, insufficient history, or fewer than 20 matching candles against
the official Hyperliquid 15m API. It derives 1h and 4h candles locally from
complete 15m buckets and replaces only those imported symbol/timeframe rows.

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

## Human Ground Truth Workstation

Start the blind historical workstation with one command:

```bash
python scripts/strategy_annotator.py
```

On 4H, 1H, and 15M, capture only the trader's actual analysis: triangles,
trendlines, and strong points. Then choose Nothing, Skip, Maybe, or Trade; a
Trade additionally records direction, entry, stop, target, confidence, and
optional notes. `Record` saves the decision and all three timeframe screenshots.

## Safety Notes

- Real order execution is not implemented.
- No live trading mode exists yet.
- No Hyperliquid account trading calls are made.
- Secrets should only be provided through `.env` or environment variables.
- If strategy evaluation is uncertain, signals should be rejected with clear reasons.
