import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { KLineChartAdapter } from "./charts/KLineChartAdapter";
import { canMutateDraft, createStrongPoint, createTrendline, createTriangle, forTimeframe, normalizeStoredDraft, planIsDirectional, redoDraftHistory, snapshotForCapture, type StoredDraft, undoDraftHistory, updateLevelCoordinates, updateStrongPoint, updateTrendline, updateTriangleVertices, withMarketState } from "./draft";
import type { Annotation, HumanTrendline, OverlayLine, PriceLevel, StrongPoint, Timeframe, Triangle } from "./types";
import "./style.css";

type Session = { session_id: string; symbol: string; replay_time: number; mode: string };
type ReplayRange = { earliest_valid: number; latest_valid: number; pre_roll_candles: number };
type Trade = { simulated_trade_id: string; status: "pending" | "open" | "stopped" | "target" | "manual_exit" | "ambiguous"; symbol: string; side: "long" | "short"; entry_price: number; stop_loss: number; take_profit: number };
type ActualTrade = { trade_id: string; entry_time: number; side: "long" | "short" };
type Candidate = { decision_time: number; side: "long" | "short" };
const timeframes: Timeframe[] = ["4h", "1h", "15m"];
const draftStorageKey = (sessionId: string) => `annotator-draft:${sessionId}`;

const api = async <T,>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};
const blank = (session: Session): Annotation => ({ annotation_id: crypto.randomUUID(), session_id: session.session_id, symbol: session.symbol, decision_time: session.replay_time, market_state: "no_structure", structures: [], trendlines: [], strong_points: [], levels: [], notes: "" });
const roleFor = (timeframe: Timeframe): Triangle["role"] => ({ "4h": "macro_parent", "1h": "local_parent", "15m": "entry" })[timeframe];
const dateInput = (timestamp: number) => new Date(timestamp).toISOString().slice(0, 16);
const updateLegacyLine = (items: Triangle[], id: string, side: "upper" | "lower", line: OverlayLine) => items.map((item) => item.structure_id === id && "upper_line" in item.geometry ? { ...item, geometry: { ...item.geometry, [`${side}_line`]: line } } : item);

function App() {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<KLineChartAdapter>();
  const operationRef = useRef<string | null>(null);
  const requestVersionRef = useRef(0);
  const [session, setSession] = useState<Session | null>(null);
  const [symbol, setSymbol] = useState("BTC");
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [annotation, setAnnotation] = useState<Annotation | null>(null);
  const [range, setRange] = useState<ReplayRange | null>(null);
  const [chosenTime, setChosenTime] = useState("");
  const [history, setHistory] = useState<StoredDraft[]>([]);
  const [redo, setRedo] = useState<StoredDraft[]>([]);
  const [snap, setSnap] = useState<"free" | "weak" | "strong">("weak");
  const [trades, setTrades] = useState<Trade[]>([]);
  const [actualTrades, setActualTrades] = useState<ActualTrade[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [status, setStatus] = useState("Start a blind historical replay to begin.");
  const [help, setHelp] = useState(false);
  const [tutorial, setTutorial] = useState(() => localStorage.getItem("annotator-tutorial-seen") !== "true");
  const [tutorialStep, setTutorialStep] = useState(0);
  const [decisionSelected, setDecisionSelected] = useState(false);
  const [decisionLockedAt, setDecisionLockedAt] = useState<number | null>(null);
  const [operation, setOperation] = useState<string | null>(null);
  const [planStep, setPlanStep] = useState<"entry_price" | "stop_loss" | "take_profit" | null>(null);

  const beginOperation = (name: string) => {
    if (operationRef.current) return false;
    operationRef.current = name; setOperation(name); return true;
  };
  const endOperation = () => { operationRef.current = null; setOperation(null); };

  const snapshot = (draft: Annotation): StoredDraft => ({ annotation: draft, decisionSelected, decisionLockedAt });
  const change = (edit: (draft: Annotation) => Annotation) => setAnnotation((draft) => {
    if (!draft) return draft;
    if (!canMutateDraft(operationRef.current)) return draft;
    setHistory((items) => [...items, snapshot(draft)]); setRedo([]);
    return edit(draft);
  });
  const rows = (current: Session, tf: Timeframe) => api<Array<Record<string, number>>>(`/sessions/${current.session_id}/candles/${tf}`);
  const apply = async (candles: Array<Record<string, number>>) => chart.current?.setCandles(candles.map((c) => ({ timestamp: c.open_time, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume })));
  const restore = (draft = annotation, tf = timeframe, editable = true) => {
    if (!draft || !chart.current) return;
    const visible = forTimeframe(draft, tf);
    chart.current.restore(visible.structures, visible.trendlines, visible.strong_points, visible.levels, visible.trade_plan ?? null, visible.side ?? null,
      (id, vertices) => editable && !operationRef.current && change((item) => ({ ...item, structures: updateTriangleVertices(item.structures, id, vertices) })),
      (id, p1, p2) => editable && !operationRef.current && change((item) => ({ ...item, trendlines: updateTrendline(item.trendlines, id, p1, p2) })),
      (id, point) => editable && !operationRef.current && change((item) => ({ ...item, strong_points: updateStrongPoint(item.strong_points, id, point) })),
      (id, side, line) => editable && !operationRef.current && change((item) => ({ ...item, structures: updateLegacyLine(item.structures, id, side, line) })),
      (id, start, end) => editable && !operationRef.current && change((item) => ({ ...item, levels: updateLevelCoordinates(item.levels, id, start, end) })),
      (key, price) => editable && !operationRef.current && change((item) => ({ ...item, trade_plan: item.trade_plan ? { ...item.trade_plan, [key]: price } : item.trade_plan })),
    );
  };
  const reload = async (current: Session, tf = timeframe, internal = false) => {
    if (operationRef.current && !internal) return;
    const version = ++requestVersionRef.current;
    const candles = await rows(current, tf);
    if (version !== requestVersionRef.current) return;
    await apply(candles); if (version !== requestVersionRef.current) return; restore(annotation, tf);
    setStatus(`${tf.toUpperCase()} · ${candles.length} closed candles · future data hidden`);
  };

  useEffect(() => { api<ReplayRange>(`/replay-range/${symbol}`).then(setRange).catch((error) => { setRange(null); setStatus(String(error)); }); }, [symbol]);
  useEffect(() => {
    const id = localStorage.getItem("annotator-session");
    if (!id) return;
    api<Session>(`/sessions/${id}`).then((saved) => {
      const stored = localStorage.getItem(draftStorageKey(saved.session_id));
      let draft = blank(saved), selected = false, lockedAt: number | null = null;
      try {
        const normalized = stored ? normalizeStoredDraft(JSON.parse(stored), saved) : null;
        if (normalized) { draft = normalized.annotation; selected = normalized.decisionSelected; lockedAt = normalized.decisionLockedAt; }
        else if (stored) { localStorage.removeItem(draftStorageKey(saved.session_id)); setStatus("Saved draft was incompatible and was cleared."); }
      } catch { localStorage.removeItem(draftStorageKey(saved.session_id)); setStatus("Saved draft was corrupt and was cleared."); }
      setSession(saved); setSymbol(saved.symbol); setAnnotation(draft); setDecisionSelected(selected); setDecisionLockedAt(lockedAt);
    }).catch(() => localStorage.removeItem("annotator-session"));
  }, []);
  useEffect(() => {
    if (session && annotation?.session_id === session.session_id)
      localStorage.setItem(draftStorageKey(session.session_id), JSON.stringify({ annotation, decisionSelected, decisionLockedAt }));
  }, [annotation, decisionLockedAt, decisionSelected, session?.session_id]);
  useEffect(() => {
    if (!session || !element.current) return;
    const adapter = new KLineChartAdapter(element.current); chart.current = adapter;
    void reload(session, timeframe, true);
    return () => { adapter.destroy(); if (chart.current === adapter) chart.current = undefined; };
  }, [session?.session_id]);
  useEffect(() => { restore(); }, [annotation, timeframe]);
  useEffect(() => { if (session) void api<Trade[]>(`/sessions/${session.session_id}/trades`).then(setTrades); }, [session?.session_id]);

  const activate = async (created: Session, message?: string) => {
    setSession(created); setAnnotation(blank(created)); setHistory([]); setRedo([]); setTrades([]); setDecisionSelected(false); setDecisionLockedAt(null); setPlanStep(null);
    localStorage.setItem("annotator-session", created.session_id);
    if (message) setStatus(message);
  };
  const start = async (selectionMode: "random" | "chosen_date") => {
    if (!beginOperation("start")) return;
    try {
      const startTime = selectionMode === "chosen_date" ? new Date(chosenTime).getTime() : undefined;
      if (selectionMode === "chosen_date" && (!chosenTime || Number.isNaN(startTime))) { setStatus("Choose a valid historical date/time."); return; }
      await activate(await api<Session>("/sessions", { method: "POST", body: JSON.stringify({ symbol, start_time: startTime, mode: "free_replay", selection_mode: selectionMode }) }));
    } catch (error) { setStatus(String(error)); } finally { endOperation(); }
  };
  const startResearch = async (mode: "reconstruct_real_trade" | "review_bot_candidate", startTime: number) => {
    if (!beginOperation("research")) return;
    try {
      await activate(await api<Session>("/sessions", { method: "POST", body: JSON.stringify({ symbol, start_time: startTime, mode, selection_mode: mode === "reconstruct_real_trade" ? "reconstruct" : "bot_review" }) }), mode === "reconstruct_real_trade" ? "Reconstruction starts before the selected entry." : "Bot-review replay started; bot geometry remains separate.");
    } catch (error) { setStatus(String(error)); } finally { endOperation(); }
  };
  const switchTimeframe = async (next: Timeframe) => {
    if (!session || !beginOperation("timeframe")) return;
    try { setTimeframe(next); await reload(session, next, true); } catch (error) { setStatus(String(error)); } finally { endOperation(); }
  };
  const advance = async (count: number) => {
    if (!session || decisionSelected || !beginOperation("advance")) return;
    try { const next = await api<Session>(`/sessions/${session.session_id}/advance`, { method: "POST", body: JSON.stringify({ count }) }); setSession(next); setAnnotation((draft) => draft ? { ...draft, decision_time: next.replay_time } : draft); await reload(next, timeframe, true); setTrades(await api<Trade[]>(`/sessions/${next.session_id}/trades`)); }
    catch (error) { setStatus(String(error)); } finally { endOperation(); }
  };
  const triangle = () => { if (!canMutateDraft(operationRef.current)) return; chart.current?.drawTriangle(snap, (vertices) => {
    const structure = createTriangle(crypto.randomUUID(), timeframe, roleFor(timeframe), vertices, snap);
    if (new URLSearchParams(window.location.search).has("triangleTrace"))
      console.debug(`[humanTriangle] createTriangle vertices ${JSON.stringify(structure.geometry.vertices)}`);
    change((draft) => ({ ...draft, structures: [...draft.structures, structure] }));
  }); };
  const trendline = () => { if (canMutateDraft(operationRef.current)) chart.current?.drawTrendline(snap, (p1, p2) => change((draft) => ({ ...draft, trendlines: [...draft.trendlines, createTrendline(crypto.randomUUID(), timeframe, p1, p2, snap)] }))); };
  const strongPoint = () => { if (canMutateDraft(operationRef.current)) chart.current?.drawStrongPoint(snap, (point) => change((draft) => ({ ...draft, strong_points: [...draft.strong_points, createStrongPoint(crypto.randomUUID(), timeframe, point, snap)] }))); };
  const plan = (key: "entry_price" | "stop_loss" | "take_profit", guided = false) => {
    if (operationRef.current) return;
    setPlanStep(key);
    chart.current?.drawHorizontal(key, snap, (point) => {
      change((draft) => ({ ...draft, trade_plan: { entry_price: draft.trade_plan?.entry_price ?? point.price, stop_loss: draft.trade_plan?.stop_loss ?? point.price, take_profit: draft.trade_plan?.take_profit ?? point.price, [key]: point.price } }));
      const next = key === "entry_price" ? "stop_loss" : key === "stop_loss" ? "take_profit" : null;
      if (guided && next) { setPlanStep(next); setStatus(next === "stop_loss" ? "Place Stop" : "Place Target"); window.setTimeout(() => plan(next, true), 0); }
      else { setPlanStep(null); setStatus(guided ? "Trade plan complete — drag any line to refine" : `Place ${key === "entry_price" ? "Entry" : key === "stop_loss" ? "Stop" : "Target"}`); }
    });
  };
  const undo = () => { if (operationRef.current || !annotation) return; const nextHistory = [...history], nextRedo = [...redo], previous = undoDraftHistory(nextHistory, nextRedo, snapshot(annotation)); if (!previous) return; setHistory(nextHistory); setRedo(nextRedo); setAnnotation(previous.annotation); setDecisionSelected(previous.decisionSelected); setDecisionLockedAt(previous.decisionLockedAt); };
  const redoAction = () => { if (operationRef.current || !annotation) return; const nextHistory = [...history], nextRedo = [...redo], next = redoDraftHistory(nextHistory, nextRedo, snapshot(annotation)); if (!next) return; setHistory(nextHistory); setRedo(nextRedo); setAnnotation(next.annotation); setDecisionSelected(next.decisionSelected); setDecisionLockedAt(next.decisionLockedAt); };
  const reset = () => { if (operationRef.current || !session || !annotation) return; if ((annotation.structures.length || annotation.trendlines.length || annotation.strong_points.length || annotation.levels.length || annotation.trade_plan) && !window.confirm("Clear only this unrecorded setup?")) return; setAnnotation(blank(session)); setHistory([]); setRedo([]); setDecisionSelected(false); setDecisionLockedAt(null); setPlanStep(null); };
  const capture = async (captured: Annotation) => {
    if (!session || !chart.current || operationRef.current !== "record") throw new Error("Chart is not exclusively owned for screenshot capture.");
    const screenshots: Record<string, string> = {};
    for (const tf of timeframes) { await apply(await rows(session, tf)); restore(captured, tf, false); const image = await chart.current.snapshotAfterRender(); if (!image) throw new Error(`Unable to capture ${tf} screenshot.`); screenshots[tf] = image; }
    await reload(session, timeframe, true); return screenshots;
  };
  const record = async () => {
    if (!session || !annotation || !decisionSelected || decisionLockedAt === null || !beginOperation("record")) return;
    if (annotation.market_state === "trade" && !planIsDirectional(annotation)) { endOperation(); setStatus("Trade plan must be LONG Stop < Entry < Target or SHORT Target < Entry < Stop."); return; }
    const captured = snapshotForCapture(annotation);
    try { const screenshots = await capture(captured); const saved = await api<Annotation>("/annotations/record", { method: "POST", body: JSON.stringify({ annotation: { ...captured, decision_time: decisionLockedAt }, screenshots, place_trade: captured.market_state === "trade" }) }); localStorage.removeItem(draftStorageKey(session.session_id)); setAnnotation(blank(session)); setHistory([]); setRedo([]); setDecisionSelected(false); setDecisionLockedAt(null); setPlanStep(null); setTrades(await api<Trade[]>(`/sessions/${session.session_id}/trades`)); setStatus(saved.market_state === "trade" ? "Decision recorded and simulated trade placed. A clean draft is ready." : "Decision recorded. A clean draft is ready."); }
    catch (error) { setStatus(`Record failed — draft kept intact: ${String(error)}`); } finally { endOperation(); }
  };
  const selectDecision = (state: Annotation["market_state"]) => {
    if (!session || operationRef.current) return;
    change((draft) => withMarketState(draft, state)); setDecisionSelected(true); setDecisionLockedAt(session.replay_time);
  };
  const manualExit = async (trade: Trade) => {
    if (!session || !beginOperation("manual-exit")) return;
    try { const candles = await rows(session, "15m"); const close = candles.at(-1)?.close; if (typeof close !== "number") throw new Error("No visible 15M close is available."); const updated = await api<Trade>(`/trades/${trade.simulated_trade_id}/manual-exit`, { method: "POST", body: JSON.stringify({ price: close, timestamp: session.replay_time }) }); setTrades((items) => items.map((item) => item.simulated_trade_id === updated.simulated_trade_id ? updated : item)); }
    catch (error) { setStatus(String(error)); } finally { endOperation(); }
  };
  const metrics = useMemo(() => annotation?.trade_plan ? { risk: Math.abs(annotation.trade_plan.entry_price - annotation.trade_plan.stop_loss), reward: Math.abs(annotation.trade_plan.take_profit - annotation.trade_plan.entry_price) } : null, [annotation]);
  useEffect(() => { const key = (event: KeyboardEvent) => { if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement || event.target instanceof HTMLTextAreaElement || operationRef.current) return; if (event.key === "ArrowRight" && !decisionSelected) void advance(event.shiftKey ? 5 : 1); if (event.key.toLowerCase() === "t") triangle(); if (event.key.toLowerCase() === "l") trendline(); if (event.key.toLowerCase() === "o") strongPoint(); if (event.key.toLowerCase() === "e") plan("entry_price"); if (event.key.toLowerCase() === "s") plan("stop_loss"); if (event.key.toLowerCase() === "p") plan("take_profit"); if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") event.shiftKey ? redoAction() : undo(); if (event.key === "Enter") void record(); if (["1", "2", "3", "4", "5"].includes(event.key)) change((draft) => ({ ...draft, confidence: Number(event.key) })); }; addEventListener("keydown", key); return () => removeEventListener("keydown", key); });

  const helpText = <><p><b>4H</b> macro parent · <b>1H</b> local parent · <b>15M</b> entry structure. Draw the triangle, trendlines, and strong points that genuinely matter.</p><p><b>Nothing here</b>: no meaningful tradable setup. <b>Valid setup — Skip</b>: real structure, no trade. <b>Maybe</b>: plausible but not convincing. <b>Trade</b>: you would actually take it.</p><p>Shortcuts: → next · Shift+→ +5 · T triangle · L trendline · O strong point · E/S/P plan · 1–5 confidence · Cmd/Ctrl+Z undo · Enter record.</p></>;
  if (!session) return <main className="start"><header><div className="brand">REPLAY <i>01</i></div><div className="live">LOCAL · BLIND HISTORICAL REPLAY</div><button disabled={operation !== null} onClick={() => setHelp(true)}>? HELP</button></header><section className="start-card"><h1>START NEW REPLAY</h1><label>Market<select disabled={operation !== null} value={symbol} onChange={(event) => setSymbol(event.target.value)}><option>BTC</option><option>ETH</option><option>SOL</option></select></label><button disabled={operation !== null} className="commit" onClick={() => void start("random")}>START RANDOM REPLAY</button><p>Random Replay is recommended for collecting human training examples. Future candles remain hidden.</p><div className="or">or</div><label>Historical date/time<input disabled={operation !== null} type="datetime-local" value={chosenTime} onChange={(event) => setChosenTime(event.target.value)} min={range ? dateInput(range.earliest_valid) : undefined} max={range ? dateInput(range.latest_valid) : undefined} /></label><button disabled={operation !== null} onClick={() => void start("chosen_date")}>START AT DATE</button>{range && <small>Available replay range: {new Date(range.earliest_valid).toLocaleString()} → {new Date(range.latest_valid).toLocaleString()}<br />Includes {range.pre_roll_candles} closed 4H candles of pre-roll.</small>}<p>{status}</p></section>{tutorial && <Tutorial step={tutorialStep} next={() => tutorialStep < 4 ? setTutorialStep(tutorialStep + 1) : (localStorage.setItem("annotator-tutorial-seen", "true"), setTutorial(false))} />}{help && <Modal close={() => setHelp(false)}>{helpText}</Modal>}</main>;
  const busy = operation !== null;
  const locked = decisionSelected || busy;
  return <main>
    <header><div className="brand">REPLAY <i>01</i></div><div className="live">HISTORICAL REPLAY · {new Date(session.replay_time).toLocaleString()}</div><button disabled={busy} onClick={() => setHelp(true)}>? HELP</button><ResearchTools disabled={busy} symbol={symbol} actualTrades={actualTrades} candidates={candidates} setActualTrades={setActualTrades} setCandidates={setCandidates} startResearch={startResearch} setStatus={setStatus} /></header>
    <section className="toolbar">{timeframes.map((tf) => <button key={tf} disabled={busy} className={timeframe === tf ? "active" : ""} onClick={() => void switchTimeframe(tf)}>{tf.toUpperCase()}</button>)}<span /><button disabled={locked} onClick={() => void advance(1)}>NEXT →</button><button disabled={locked} onClick={() => void advance(5)}>+5</button></section>
    <section className="workspace"><div className="chart"><div ref={element} className="chart-canvas" /><p>{status}</p></div><aside>
      <h2>CURRENT SETUP</h2>
      <p className="decision-state">{decisionSelected ? `DECISION LOCKED · ${new Date(decisionLockedAt!).toLocaleString()}` : "NO DECISION SELECTED"}</p>
      <div className="decisions">{([ ["no_structure", "NOTHING HERE"], ["valid_triangle_no_trade", "VALID SETUP — SKIP"], ["maybe_setup", "MAYBE"], ["trade", "TRADE"] ] as const).map(([value, label]) => <button disabled={busy} key={value} className={decisionSelected && annotation?.market_state === value ? "selected" : ""} onClick={() => selectDecision(value)}>{label}</button>)}</div>
      <div className="direction"><button disabled={busy} className={annotation?.side === "long" ? "selected" : ""} onClick={() => change((draft) => ({ ...draft, side: "long" }))}>LONG</button><button disabled={busy} className={annotation?.side === "short" ? "selected" : ""} onClick={() => change((draft) => ({ ...draft, side: "short" }))}>SHORT</button></div>
      <label>Confidence<div className="confidence">{[1,2,3,4,5].map((value) => <button disabled={busy} key={value} className={annotation?.confidence === value ? "selected" : ""} onClick={() => change((draft) => ({ ...draft, confidence: value }))}>{value}</button>)}</div></label>
      {annotation?.side && <><button disabled={busy} onClick={() => { setStatus("Place Entry"); plan("entry_price", true); }}>PLACE TRADE PLAN</button><div className="plan-actions"><button disabled={busy} className={planStep === "entry_price" ? "active" : ""} onClick={() => plan("entry_price")}>ENTRY</button><button disabled={busy} className={planStep === "stop_loss" ? "active" : ""} onClick={() => plan("stop_loss")}>STOP</button><button disabled={busy} className={planStep === "take_profit" ? "active" : ""} onClick={() => plan("take_profit")}>TARGET</button></div></>}
      {metrics && <small>Entry {annotation?.trade_plan?.entry_price.toFixed(2)}<br />Stop {annotation?.trade_plan?.stop_loss.toFixed(2)}<br />Target {annotation?.trade_plan?.take_profit.toFixed(2)}<br />Risk {(metrics.risk / (annotation?.trade_plan?.entry_price || 1) * 100).toFixed(2)}% · Reward {(metrics.reward / (annotation?.trade_plan?.entry_price || 1) * 100).toFixed(2)}% · R:R {(metrics.reward / metrics.risk).toFixed(2)}</small>}
      <button className="commit" disabled={busy || !decisionSelected} onClick={() => void record()}>{annotation?.market_state === "trade" ? "RECORD & PLACE TRADE" : "RECORD & CONTINUE"}</button>
      <section className="active-trades">{trades.map((trade) => <div key={trade.simulated_trade_id}><b>{trade.symbol} {trade.side.toUpperCase()} · {trade.status.toUpperCase()}</b><small>Entry {trade.entry_price} · Stop {trade.stop_loss} · Target {trade.take_profit}</small>{trade.status === "open" && <button disabled={busy} onClick={() => void manualExit(trade)}>MANUAL EXIT AT CURRENT CLOSE</button>}</div>)}</section>
    </aside></section>
    <section className="drawing-toolbar"><button disabled={busy} onClick={triangle}>△ TRIANGLE</button><button disabled={busy} onClick={trendline}>╱ TRENDLINE</button><button disabled={busy} onClick={strongPoint}>● STRONG POINT</button><select disabled={busy} value={snap} onChange={(event) => setSnap(event.target.value as typeof snap)}><option value="free">Free draw</option><option value="weak">Weak snap</option><option value="strong">Strong snap</option></select><button disabled={busy} onClick={undo}>UNDO</button><button disabled={busy} onClick={redoAction}>REDO</button><button disabled={busy} onClick={reset}>RESET CURRENT SETUP</button></section>{help && <Modal close={() => setHelp(false)}>{helpText}</Modal>}
  </main>;
}

function ResearchTools({ disabled, symbol, actualTrades, candidates, setActualTrades, setCandidates, startResearch, setStatus }: { disabled: boolean; symbol: string; actualTrades: ActualTrade[]; candidates: Candidate[]; setActualTrades: (items: ActualTrade[]) => void; setCandidates: (items: Candidate[]) => void; startResearch: (mode: "reconstruct_real_trade" | "review_bot_candidate", time: number) => Promise<void>; setStatus: (value: string) => void }) { return <details><summary>RESEARCH TOOLS</summary><p>Secondary only: never use these for blind Batch 1 capture.</p><button disabled={disabled} onClick={() => void api<ActualTrade[]>(`/actual-trades?symbol=${symbol}`).then(setActualTrades).catch((error) => setStatus(String(error)))}>LOAD REAL TRADES</button>{actualTrades.map((trade) => <button disabled={disabled} key={trade.trade_id} onClick={() => void startResearch("reconstruct_real_trade", trade.entry_time)}>RECONSTRUCT {trade.trade_id} · {new Date(trade.entry_time).toLocaleString()} · {trade.side}</button>)}<button disabled={disabled} onClick={() => void api<Candidate[]>(`/bot-candidates?symbol=${symbol}&limit=25`).then(setCandidates).catch((error) => setStatus(String(error)))}>LOAD BOT CANDIDATES</button>{candidates.map((candidate, index) => <button disabled={disabled} key={`${candidate.decision_time}-${index}`} onClick={() => void startResearch("review_bot_candidate", candidate.decision_time)}>REVIEW {new Date(candidate.decision_time).toLocaleString()} · {candidate.side}</button>)}</details>; }
function Modal({ children, close }: { children: React.ReactNode; close: () => void }) { return <div className="modal"><section><button className="close" onClick={close}>×</button><h2>HELP</h2>{children}</section></div>; }
function Tutorial({ step, next }: { step: number; next: () => void }) { const text = ["This is a blind historical replay. Everything after the current replay point is hidden. Trade as if the market were live.", "Use 4H, 1H and 15M exactly as you normally do.", "Draw the triangles, trendlines, and strong points that genuinely influence your decision.", "If you would trade, choose Long or Short and position Entry, Stop and Target.", "Press Record. The workstation saves your decision and screenshots automatically."][step]; return <div className="modal"><section><small>{step + 1} / 5</small><p>{text}</p><button className="commit" onClick={next}>{step === 4 ? "START FIRST REPLAY" : "NEXT"}</button></section></div>; }
createRoot(document.getElementById("root")!).render(<App />);
