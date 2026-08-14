# Nested MTF Triangle Research Status

## Classification

**NO ROBUST CANDIDATE.** The completed baseline controls are rejected; no final
holdout has been run.

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

All currently defined zone-filter controls have been evaluated and recorded in
the immutable ledger. The penalty-only baseline is negative across the locked
periods (785 trades, -0.081R aggregate expectancy, PF 0.888), and the hard
filters sacrifice sample size without producing cross-symbol robustness.

The final holdout remains locked. A future research cycle must begin with a new
predeclared hypothesis and preserve the same data, period, and sample gates;
it must not tune to these validation outcomes.
