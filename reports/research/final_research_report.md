# Nested MTF Triangle Structural Research — Cycle 1

## Final classification

**NO ROBUST STRUCTURAL EDGE FOUND YET**

The final holdout was not run.

## Dataset and protocol

- Provider: verified Binance USD-M perpetual 15m canonical dataset.
- Markets: BTC, ETH, SOL.
- Train: 2025-01-01 through 2025-12-21; validation: 2025-12-22 through 2026-04-18.
- Final holdout: 2026-04-19 onward, untouched.
- Trade-level analysis: 571 closed train trades under the penalty-only control.

## Structural diagnostics

The row-level dataset is `structural_diagnostics.csv`. It includes child
triangle geometry/cleanliness, parent relation/location, 15m/1h/4h trend,
breakout quality, and nearest opposite-zone room measured at the decision time.

No measured parent-child geometry, trend, room-to-move, or breakout feature
produced a large, directionally consistent effect across BTC, ETH, and SOL.
The score is not monotonic: the high-score buckets are often worse than middle
or low buckets, and their ordering differs materially by market.

## Top findings

1. Ascending child triangles were negative in train for BTC (-0.154R), ETH
   (-0.381R), and SOL (-0.129R). Excluding them improved validation across all
   three symbols, but only to +0.029R / PF 1.042 combined and with negative
   train performance. This is insufficient to promote.
2. Child containment/overlap is informative in ETH and SOL train data, but a
   90% containment gate did not generalize to validation.
3. Setups with both parents were poor in the small train sample, but excluding
   them left ETH negative in both periods.
4. Stronger breakout bodies improved some train outcomes but were negative on
   validation across all three symbols.
5. Greater computed room to an opposite zone and parent convergence did not
   have stable cross-market signs; they are not justified hard filters.

## Experiments

| ID | Hypothesis | Decision |
| --- | --- | --- |
| R006 | Remove 1h parent score | REJECT — no trade-selection impact |
| R007 | Require 90% parent containment | REJECT — validation negative |
| R008 | Exclude ascending child triangles | INCONCLUSIVE — positive validation but below gates |
| R009 | Exclude both-parent setups | REJECT — ETH remained negative |
| R010 | Require 50% breakout body | REJECT — validation negative on all symbols |

No experiment was kept. Rejected/inconclusive changes were reverted rather
than stacked.

## Best resulting strategy

The original penalty-only nested-MTF control remains the best known baseline,
not a candidate: it looks for a 15m breakout from a triangle nested in 1h or
4h structure, scores parent/trend/breakout/zone context, and uses fixed
stop/target risk management. It does not demonstrate a positive cross-market
selection edge.

## Baseline results

| Period | Trades | Expectancy R | PF |
| --- | ---: | ---: | ---: |
| Train | 571 | -0.080 | 0.888 |
| Validation | 214 | -0.083 | 0.886 |

Train by symbol: BTC +0.002R / PF 1.001 (174), ETH -0.106R / PF 0.852 (210),
SOL -0.127R / PF 0.826 (187). Validation: BTC -0.059R / PF 0.916 (65), ETH
-0.102R / PF 0.856 (81), SOL -0.079R / PF 0.890 (68).

Longs were persistently weak outside BTC train; validation long expectancy was
BTC -0.198R, ETH -0.144R, SOL -0.237R. Validation shorts were better but not
uniformly sufficient: BTC +0.067R, ETH -0.065R, SOL +0.070R. Monthly results
are dispersed across the train period, with no credible, stable positive
concentration that supports a regime-specific rule.

## What appears missing

The current automated representation can recognize geometrically valid nested
triangles, but its parent relation is mostly a containment test. It does not
capture the discretionary distinction between a meaningful parent structural
location and coincidental multi-timeframe overlap. The present score also does
not rank expected value. Further work should acquire or define an independently
observable representation of parent support/resistance significance, impulse
context, or regime rather than continue threshold tuning on these features.
