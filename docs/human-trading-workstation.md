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

Choose a structure role, press **T TRIANGLE**, and draw the upper then lower boundary directly on the KLineChart. Use the role selector for macro parent, local parent, entry, or other. The adapter persists timestamp/price coordinates, never pixels. Use free, weak, or strong snapping as appropriate. Choose a level kind and press **H LEVEL** for optional support, resistance, strong level, or zone annotations. Existing lines are draggable on-chart; the × controls delete a saved drawing. Undo/redo applies to the current unsaved annotation.

Set market state, direction, and confidence. Press **DRAW** beside Entry, Stop Loss, or Take Profit to place each draggable horizontal line; manual price entry is also available. Those price placements are authoritative. Commit the annotation, then place the simulated trade. As replay advances, entry and exit are simulated; an ambiguous candle where both stop and target touch is handled conservatively as a stop. An open trade can be manually exited at the current replay time.

Edits retain the previous annotation payload in `annotation_revisions`. Reloading restores the latest session, drawings, trade plan, and simulated trades. Saving automatically captures KLineChart PNGs for 4h, 1h, and 15m alongside the exact structured annotation.

## Research exports

Freeze a batch without overwriting old ones:

```bash
python scripts/export_human_ground_truth.py
python scripts/extract_human_features.py
```

The batch has JSONL annotations/trades, manifest metadata, and SHA-256 sums. Do not edit a frozen batch; correct the source annotation and create a new batch instead.

`data/human_ground_truth/actual_trades.csv` can be used as the source for reconstruction sessions: start a replay at or before the recorded entry time, redraw structures without future candles, and save the reconstructed annotation separately from the original trade record.

Place an `actual_trades.csv` file at that path and restart the workstation; it is imported locally. Press **RECONSTRUCT** to begin before the first selected real-trade entry candle. Press **BOT REVIEW** to list baseline candidates, select one, redraw independently, save, then mark it Correct, Wrong, or Redraw. The bot candidate payload is stored separately and never replaces human geometry.
