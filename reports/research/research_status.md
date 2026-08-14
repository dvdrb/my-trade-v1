# Nested MTF Triangle Research Status

## Classification

**NEEDS MORE RESEARCH — baseline controls in progress.** No strategy candidate
has been selected, and no final holdout has been run.

## What was verified

- The backtest evaluates a closed execution candle and places an accepted
  signal only on the following candle's open.
- Parent-timeframe context is restricted to candles closed as of the execution
  candle's close. Existing tests cover unfinished 1h and 4h candle exclusion.
- Fees, slippage, actual-entry risk/reward revalidation, and conservative
  stop-first treatment of ambiguous stop/target candles are covered by tests.

## Research-data gate

The independent Binance USD-M research store now has 56,673 continuous 15m
candles per BTC, ETH, and SOL from 2025-01-01 through 2026-08-14 08:00 UTC,
with 14,168 locally derived 1h candles and 3,542 derived 4h candles per
symbol. The provider-aware audit passed after archive checksum, canonical hash,
OHLC, continuity, common-grid, and derivation checks. The execution-venue
Hyperliquid history remains separate and is used only for compatibility
diagnostics.

The chronological split is frozen: train through 2025-12-21, validation from
2025-12-22 through 2026-04-18, and final holdout from 2026-04-19 onward.
Only train and validation are currently being used for selection.

## Required next step

Complete the remaining baseline controls, record every result in the immutable
experiment ledger, and test only bounded hypotheses that survive the controls.
The final holdout remains locked until a candidate passes validation gates.
