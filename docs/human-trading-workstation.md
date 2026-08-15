# Human Trading Workstation

The workstation is a local replay instrument for collecting the trader's own market structure and trade-plan decisions. It never sends orders and does not change the existing strategy.

## Launch

Install project dependencies (including FastAPI and Uvicorn), then run:

```bash
python scripts/strategy_annotator.py
```

The first launch installs and builds the pinned local frontend dependencies if necessary, then the browser opens at `http://127.0.0.1:8765`. The backend only reads the local SQLite candle store. First import or fetch the approved Binance USD-M research candles into `data/bot.sqlite3`.

## Workflow

Choose BTC, ETH, or SOL, press **Start Session**, and switch among 4h, 1h, and 15m. All panes request candles from the replay backend, which returns only candles at or before the session replay time. Use **Next** or **+5** (Right Arrow / Shift+Right) to advance.

Draw upper and lower triangle boundaries using the chart tool. Save them as a structure with its timeframe and role: macro parent, local parent, entry, or other. The adapter persists timestamp/price coordinates, never pixels. Use free, weak, or strong snapping as appropriate. Add optional support, resistance, strong level, or zone annotations.

Set market state, direction, and confidence. For a trade, visually place Entry, Stop Loss, and Take Profit; those price placements are authoritative. Optional SL and TP tags capture the reason. Commit the annotation, then place the simulated trade. As replay advances, entry and exit are simulated; an ambiguous candle where both stop and target touch is handled conservatively as a stop.

Edits retain the previous annotation payload in `annotation_revisions`. Reloading restores persisted data. Screenshots should be exported from KLineChart's native image conversion alongside saved annotations in the UI integration.

## Research exports

Freeze a batch without overwriting old ones:

```bash
python scripts/export_human_ground_truth.py
python scripts/extract_human_features.py
```

The batch has JSONL annotations/trades, manifest metadata, and SHA-256 sums. Do not edit a frozen batch; correct the source annotation and create a new batch instead.

`data/human_ground_truth/actual_trades.csv` can be used as the source for reconstruction sessions: start a replay at or before the recorded entry time, redraw structures without future candles, and save the reconstructed annotation separately from the original trade record.
