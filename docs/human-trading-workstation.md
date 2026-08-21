# Human Trading Workstation

The workstation is a local, blind historical replay instrument for collecting human trading decisions. It never sends orders and it does not modify the trading strategy.

## Start

```bash
python scripts/prepare_human_replay_data.py
python scripts/strategy_annotator.py
```

The one-time preparation step copies only the approved train/validation candles from the local checksum-verified research database into `data/human_replay.sqlite3`; it never copies final-holdout data and never changes `data/bot.sqlite3`. The launcher rebuilds the local UI by default so it cannot serve stale source. Use `--skip-ui-build` only when deliberately reusing an existing build.

## Normal workflow

```text
Start random replay
→ inspect 4H
→ inspect 1H
→ inspect 15M
→ draw what matters
→ choose a decision
→ if Trade, place a plan
→ Record
→ continue
```

Random Replay is the normal Batch 1 mode. The backend chooses only timestamps inside the approved train/validation research interval from `app/config/research_periods.yaml`; the final financial holdout cannot be entered. A replay also requires 200 closed 4H candles of pre-roll, and every chart request is bounded and future-safe.

Each Record freezes one human decision and creates a clean, new draft. Do not use a previously recorded decision as a draft for a later market point. A saved decision is immutable; intentional corrections are revisions, with original payloads and screenshots retained.

## Decision definitions

- **Nothing here** — no meaningful tradable setup worth recording.
- **Valid setup — Skip** — a real structure exists, but you would not take it.
- **Maybe** — plausible, but not convincing enough to trade normally.
- **Trade** — you would actually take it if live.

For Trade, choose Long or Short and place Entry, Stop, and Target. Long requires `SL < Entry < TP`; Short requires `TP < Entry < SL`. Trade placement occurs only after the decision and all screenshots are saved.

## Keyboard shortcuts

```text
Right Arrow       next candle
Shift + Right     +5 candles
T / H / Z         triangle / level / zone
E / S / P         entry / stop / target
1–5               confidence
Cmd/Ctrl+Z        undo
Cmd/Ctrl+Shift+Z  redo
Enter             record
```

Shortcuts are disabled while typing in an input, select, textarea, or date picker. Help is always available from `? Help`.

## Resume and research tools

The active replay session is restored on refresh. Main capture mode intentionally does not show outcomes, PnL, win rate, or bot geometry. Bot Review and real-trade reconstruction belong in Research Tools and should not be used for primary blind Batch 1 collection.

## Export a batch

```bash
python scripts/export_human_ground_truth.py
python scripts/verify_human_ground_truth_batch.py data/human_ground_truth/batches/batch_001
```

Exports are immutable: an existing batch is never overwritten. The manifest includes range, counts, symbols, screenshots, canonical screenshot revisions, and source commit where available. Verification checks JSONL schemas, checksums, unique annotation IDs, trade references, and screenshot presence.

## Important research rules

- Do not redraw because a trade lost.
- Do not inspect future candles.
- Do not use Bot Review for primary Batch 1 collection.
- Do not access the final financial holdout.
