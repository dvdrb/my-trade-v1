# Nested MTF Triangle Research Status

## Classification

**NEEDS MORE RESEARCH — blocked by data quality.** No strategy candidate has
been selected, and no final holdout has been run.

## What was verified

- The backtest evaluates a closed execution candle and places an accepted
  signal only on the following candle's open.
- Parent-timeframe context is restricted to candles closed as of the execution
  candle's close. Existing tests cover unfinished 1h and 4h candle exclusion.
- Fees, slippage, actual-entry risk/reward revalidation, and conservative
  stop-first treatment of ambiguous stop/target candles are covered by tests.

## Data gate

The planned protocol requires a continuous common BTC/ETH/SOL history of at
least 20,000 15m candles, 5,000 1h candles, and 2,000 4h candles per symbol.
The available database fails the 15m requirement for every symbol. BTC also
has one internal 1h gap. The current Hyperliquid public candle endpoint
returned zero BTC 15m candles for an explicit historical request ending before
the retained range, so pagination cannot recover the missing period.

Existing validation reports are therefore exploratory only; they must not be
used to select a strategy or to establish a train/validation/holdout split.

## Required next step

Import a verified, continuous historical source for BTC, ETH, and SOL at 15m,
1h, and 4h. Then run `python scripts/audit_research_data.py`; it exits
nonzero until the dataset meets the research gate. Only after it passes should
the chronological split boundaries be frozen and controlled experiments begin.
