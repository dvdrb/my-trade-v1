import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { KLineChartAdapter } from "./charts/KLineChartAdapter";
import { forTimeframe, updateLevelCoordinates, withMarketState } from "./draft";
import type { Annotation, OverlayLine, PriceLevel, Timeframe, TradePlan, Triangle } from "./types";
import "./style.css";

type Session = { session_id: string; symbol: string; replay_time: number; mode: string };
type ReplayRange = { earliest_valid: number; latest_valid: number; pre_roll_candles: number };
type Trade = { simulated_trade_id: string; status: string };
type ActualTrade = { trade_id: string; entry_time: number; side: "long" | "short" };
type Candidate = { decision_time: number; side: "long" | "short" };
const timeframes: Timeframe[] = ["4h", "1h", "15m"];

const api = async <T,>(path: string, options?: RequestInit): Promise<T> => {
  const response = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...options });
  if (!response.ok) throw new Error(await response.text());
  return response.json();
};
const blank = (session: Session): Annotation => ({ annotation_id: crypto.randomUUID(), session_id: session.session_id, symbol: session.symbol, decision_time: session.replay_time, market_state: "no_structure", structures: [], levels: [], notes: "" });
const roleFor = (timeframe: Timeframe): Triangle["role"] => ({ "4h": "macro_parent", "1h": "local_parent", "15m": "entry" })[timeframe];
const dateInput = (timestamp: number) => new Date(timestamp).toISOString().slice(0, 16);
const updateLine = (items: Triangle[], id: string, side: "upper" | "lower", line: OverlayLine) => items.map((item) => item.structure_id === id ? { ...item, geometry: { ...item.geometry, [`${side}_line`]: line } } : item);

function App() {
  const element = useRef<HTMLDivElement>(null);
  const chart = useRef<KLineChartAdapter>();
  const [session, setSession] = useState<Session | null>(null);
  const [symbol, setSymbol] = useState("BTC");
  const [timeframe, setTimeframe] = useState<Timeframe>("15m");
  const [annotation, setAnnotation] = useState<Annotation | null>(null);
  const [range, setRange] = useState<ReplayRange | null>(null);
  const [chosenTime, setChosenTime] = useState("");
  const [history, setHistory] = useState<Annotation[]>([]);
  const [redo, setRedo] = useState<Annotation[]>([]);
  const [levelKind, setLevelKind] = useState<PriceLevel["kind"]>("strong_level");
  const [snap, setSnap] = useState<"free" | "weak" | "strong">("weak");
  const [trades, setTrades] = useState<Trade[]>([]);
  const [actualTrades, setActualTrades] = useState<ActualTrade[]>([]);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [status, setStatus] = useState("Start a blind historical replay to begin.");
  const [help, setHelp] = useState(false);
  const [tutorial, setTutorial] = useState(() => localStorage.getItem("annotator-tutorial-seen") !== "true");
  const [tutorialStep, setTutorialStep] = useState(0);

  const change = (edit: (draft: Annotation) => Annotation) => setAnnotation((draft) => {
    if (!draft) return draft;
    setHistory((items) => [...items, draft]); setRedo([]);
    return edit(draft);
  });
  const rows = (current: Session, tf: Timeframe) => api<Array<Record<string, number>>>(`/sessions/${current.session_id}/candles/${tf}`);
  const apply = async (candles: Array<Record<string, number>>) => chart.current?.setCandles(candles.map((c) => ({ timestamp: c.open_time, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume })));
  const restore = (draft = annotation, tf = timeframe, editable = true) => {
    if (!draft || !chart.current) return;
    const visible = forTimeframe(draft, tf);
    chart.current.restore(visible.structures, visible.levels, visible.trade_plan ?? null, visible.side ?? null,
      (id, side, line) => editable && change((item) => ({ ...item, structures: updateLine(item.structures, id, side, line) })),
      (id, start, end) => editable && change((item) => ({ ...item, levels: updateLevelCoordinates(item.levels, id, start, end) })),
      (key, price) => editable && change((item) => ({ ...item, trade_plan: item.trade_plan ? { ...item.trade_plan, [key]: price } : item.trade_plan })),
    );
  };
  const reload = async (current: Session, tf = timeframe) => {
    const candles = await rows(current, tf); await apply(candles); restore(annotation, tf);
    setStatus(`${tf.toUpperCase()} · ${candles.length} closed candles · future data hidden`);
  };

  useEffect(() => { api<ReplayRange>(`/replay-range/${symbol}`).then(setRange).catch((error) => { setRange(null); setStatus(String(error)); }); }, [symbol]);
  useEffect(() => {
    const id = localStorage.getItem("annotator-session");
    if (!id) return;
    api<Session>(`/sessions/${id}`).then((saved) => { setSession(saved); setSymbol(saved.symbol); setAnnotation(blank(saved)); }).catch(() => localStorage.removeItem("annotator-session"));
  }, []);
  useEffect(() => {
    if (!session || !element.current) return;
    const adapter = new KLineChartAdapter(element.current); chart.current = adapter;
    void reload(session);
    return () => { adapter.destroy(); if (chart.current === adapter) chart.current = undefined; };
  }, [session?.session_id]);
  useEffect(() => { restore(); }, [annotation, timeframe]);
  useEffect(() => { if (session) void api<Trade[]>(`/sessions/${session.session_id}/trades`).then(setTrades); }, [session?.session_id]);

  const activate = async (created: Session, message?: string) => {
    setSession(created); setAnnotation(blank(created)); setHistory([]); setRedo([]); setTrades([]);
    localStorage.setItem("annotator-session", created.session_id);
    if (message) setStatus(message);
  };
  const start = async (selectionMode: "random" | "chosen_date") => {
    try {
      const startTime = selectionMode === "chosen_date" ? new Date(chosenTime).getTime() : undefined;
      if (selectionMode === "chosen_date" && (!chosenTime || Number.isNaN(startTime))) return setStatus("Choose a valid historical date/time.");
      await activate(await api<Session>("/sessions", { method: "POST", body: JSON.stringify({ symbol, start_time: startTime, mode: "free_replay", selection_mode: selectionMode }) }));
    } catch (error) { setStatus(String(error)); }
  };
  const startResearch = async (mode: "reconstruct_real_trade" | "review_bot_candidate", startTime: number) => {
    try {
      await activate(await api<Session>("/sessions", { method: "POST", body: JSON.stringify({ symbol, start_time: startTime, mode, selection_mode: mode === "reconstruct_real_trade" ? "reconstruct" : "bot_review" }) }), mode === "reconstruct_real_trade" ? "Reconstruction starts before the selected entry." : "Bot-review replay started; bot geometry remains separate.");
    } catch (error) { setStatus(String(error)); }
  };
  const advance = async (count: number) => { if (!session) return; try { const next = await api<Session>(`/sessions/${session.session_id}/advance`, { method: "POST", body: JSON.stringify({ count }) }); setSession(next); setAnnotation((draft) => draft ? { ...draft, decision_time: next.replay_time } : draft); await reload(next); setTrades(await api<Trade[]>(`/sessions/${next.session_id}/trades`)); } catch (error) { setStatus(String(error)); } };
  const triangle = () => chart.current?.drawSegment("upper", snap, (upper) => chart.current?.drawSegment("lower", snap, (lower) => change((draft) => ({ ...draft, structures: [...draft.structures, { structure_id: crypto.randomUUID(), timeframe, role: roleFor(timeframe), geometry: { upper_line: upper, lower_line: lower, snap_mode: snap } }] }))));
  const zone = () => chart.current?.drawSegment("zone", snap, (first) => chart.current?.drawSegment("zone-end", snap, (second) => change((draft) => ({ ...draft, levels: [...draft.levels, { level_id: crypto.randomUUID(), timeframe, kind: "strong_zone", start: first.p1, end: second.p2 }] }))));
  const level = () => levelKind === "strong_zone" ? zone() : chart.current?.drawHorizontal("level", snap, (point) => change((draft) => ({ ...draft, levels: [...draft.levels, { level_id: crypto.randomUUID(), timeframe, kind: levelKind, start: point }] })));
  const plan = (key: keyof TradePlan) => chart.current?.drawHorizontal(key, snap, (point) => change((draft) => ({ ...draft, trade_plan: { entry_price: draft.trade_plan?.entry_price ?? point.price, stop_loss: draft.trade_plan?.stop_loss ?? point.price, take_profit: draft.trade_plan?.take_profit ?? point.price, [key]: point.price } })));
  const undo = () => { const previous = history.at(-1); if (!previous) return; setHistory((items) => items.slice(0, -1)); if (annotation) setRedo((items) => [...items, annotation]); setAnnotation(previous); };
  const redoAction = () => { const next = redo.at(-1); if (!next) return; setRedo((items) => items.slice(0, -1)); if (annotation) setHistory((items) => [...items, annotation]); setAnnotation(next); };
  const reset = () => { if (!session || !annotation) return; if ((annotation.structures.length || annotation.levels.length || annotation.trade_plan) && !window.confirm("Clear only this unrecorded setup?")) return; setAnnotation(blank(session)); setHistory([]); setRedo([]); };
  const capture = async () => {
    if (!session || !annotation || !chart.current) throw new Error("Chart is not ready for screenshot capture.");
    const screenshots: Record<string, string> = {};
    for (const tf of timeframes) { await apply(await rows(session, tf)); restore(annotation, tf, false); const image = await chart.current.snapshotAfterRender(); if (!image) throw new Error(`Unable to capture ${tf} screenshot.`); screenshots[tf] = image; }
    await reload(session, timeframe); return screenshots;
  };
  const record = async () => { if (!session || !annotation) return; try { const screenshots = await capture(); const saved = await api<Annotation>("/annotations/record", { method: "POST", body: JSON.stringify({ annotation: { ...annotation, decision_time: session.replay_time }, screenshots, place_trade: annotation.market_state === "trade" }) }); setAnnotation(blank(session)); setHistory([]); setRedo([]); setTrades(await api<Trade[]>(`/sessions/${session.session_id}/trades`)); setStatus(saved.market_state === "trade" ? "Decision recorded and simulated trade placed. A clean draft is ready." : "Decision recorded. A clean draft is ready."); } catch (error) { setStatus(`Record failed — draft kept intact: ${String(error)}`); } };
  const metrics = useMemo(() => annotation?.trade_plan ? { risk: Math.abs(annotation.trade_plan.entry_price - annotation.trade_plan.stop_loss), reward: Math.abs(annotation.trade_plan.take_profit - annotation.trade_plan.entry_price) } : null, [annotation]);
  useEffect(() => { const key = (event: KeyboardEvent) => { if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement || event.target instanceof HTMLTextAreaElement) return; if (event.key === "ArrowRight") void advance(event.shiftKey ? 5 : 1); if (event.key.toLowerCase() === "t") triangle(); if (event.key.toLowerCase() === "h") level(); if (event.key.toLowerCase() === "z" && !(event.metaKey || event.ctrlKey)) zone(); if (event.key.toLowerCase() === "e") plan("entry_price"); if (event.key.toLowerCase() === "s") plan("stop_loss"); if (event.key.toLowerCase() === "p") plan("take_profit"); if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") event.shiftKey ? redoAction() : undo(); if (event.key === "Enter") void record(); if (["1", "2", "3", "4", "5"].includes(event.key)) change((draft) => ({ ...draft, confidence: Number(event.key) })); }; addEventListener("keydown", key); return () => removeEventListener("keydown", key); });

  const helpText = <><p><b>4H</b> macro parent · <b>1H</b> local parent · <b>15M</b> entry structure.</p><p><b>Nothing here</b>: no meaningful tradable setup. <b>Valid setup — Skip</b>: real structure, no trade. <b>Maybe</b>: plausible but not convincing. <b>Trade</b>: you would actually take it.</p><p>Shortcuts: → next · Shift+→ +5 · T triangle · H level · Z zone · E/S/P plan · 1–5 confidence · Cmd/Ctrl+Z undo · Enter record.</p></>;
  if (!session) return <main className="start"><header><div className="brand">REPLAY <i>01</i></div><div className="live">LOCAL · BLIND HISTORICAL REPLAY</div><button onClick={() => setHelp(true)}>? HELP</button></header><section className="start-card"><h1>START NEW REPLAY</h1><label>Market<select value={symbol} onChange={(event) => setSymbol(event.target.value)}><option>BTC</option><option>ETH</option><option>SOL</option></select></label><button className="commit" onClick={() => void start("random")}>START RANDOM REPLAY</button><p>Random Replay is recommended for collecting human training examples. Future candles remain hidden.</p><div className="or">or</div><label>Historical date/time<input type="datetime-local" value={chosenTime} onChange={(event) => setChosenTime(event.target.value)} min={range ? dateInput(range.earliest_valid) : undefined} max={range ? dateInput(range.latest_valid) : undefined} /></label><button onClick={() => void start("chosen_date")}>START AT DATE</button>{range && <small>Available replay range: {new Date(range.earliest_valid).toLocaleString()} → {new Date(range.latest_valid).toLocaleString()}<br />Includes {range.pre_roll_candles} closed 4H candles of pre-roll.</small>}<p>{status}</p></section>{tutorial && <Tutorial step={tutorialStep} next={() => tutorialStep < 4 ? setTutorialStep(tutorialStep + 1) : (localStorage.setItem("annotator-tutorial-seen", "true"), setTutorial(false))} />}{help && <Modal close={() => setHelp(false)}>{helpText}</Modal>}</main>;
  return <main><header><div className="brand">REPLAY <i>01</i></div><div className="live">HISTORICAL REPLAY · {new Date(session.replay_time).toLocaleString()}</div><button onClick={() => setHelp(true)}>? HELP</button><ResearchTools symbol={symbol} actualTrades={actualTrades} candidates={candidates} setActualTrades={setActualTrades} setCandidates={setCandidates} startResearch={startResearch} setStatus={setStatus} /></header><section className="toolbar">{timeframes.map((tf) => <button key={tf} className={timeframe === tf ? "active" : ""} onClick={() => { setTimeframe(tf); void reload(session, tf); }}>{tf.toUpperCase()}</button>)}<span /><button onClick={() => void advance(1)}>NEXT →</button><button onClick={() => void advance(5)}>+5</button></section><section className="workspace"><div className="chart"><div ref={element} className="chart-canvas" /><p>{status}</p></div><aside><h2>CURRENT SETUP</h2><div className="decisions">{([ ["no_structure", "NOTHING HERE"], ["valid_triangle_no_trade", "VALID SETUP — SKIP"], ["maybe_setup", "MAYBE"], ["trade", "TRADE"] ] as const).map(([value, label]) => <button key={value} className={annotation?.market_state === value ? "selected" : ""} onClick={() => change((draft) => withMarketState(draft, value))}>{label}</button>)}</div><div className="direction"><button className={annotation?.side === "long" ? "selected" : ""} onClick={() => change((draft) => ({ ...draft, side: "long" }))}>LONG</button><button className={annotation?.side === "short" ? "selected" : ""} onClick={() => change((draft) => ({ ...draft, side: "short" }))}>SHORT</button></div><label>Confidence<div className="confidence">{[1,2,3,4,5].map((value) => <button key={value} className={annotation?.confidence === value ? "selected" : ""} onClick={() => change((draft) => ({ ...draft, confidence: value }))}>{value}</button>)}</div></label>{annotation?.side && <button onClick={() => { plan("entry_price"); setStatus("Place Entry, then Stop, then Target. Drag any line to refine it."); }}>PLACE TRADE PLAN</button>}{metrics && <small>Entry {annotation?.trade_plan?.entry_price.toFixed(2)}<br />Stop {annotation?.trade_plan?.stop_loss.toFixed(2)}<br />Target {annotation?.trade_plan?.take_profit.toFixed(2)}<br />Risk {(metrics.risk / (annotation?.trade_plan?.entry_price || 1) * 100).toFixed(2)}% · Reward {(metrics.reward / (annotation?.trade_plan?.entry_price || 1) * 100).toFixed(2)}% · R:R {(metrics.reward / metrics.risk).toFixed(2)}</small>}<button className="commit" onClick={() => void record()}>{annotation?.market_state === "trade" ? "RECORD & PLACE TRADE" : "RECORD & CONTINUE"}</button><small>Session<br />Trades: {trades.length} · outcomes stay out of capture view</small></aside></section><section className="drawing-toolbar"><button onClick={triangle}>△ TRIANGLE</button><select value={levelKind} onChange={(event) => setLevelKind(event.target.value as PriceLevel["kind"])}><option value="strong_level">Strong level</option><option value="support">Support</option><option value="resistance">Resistance</option><option value="strong_zone">Zone</option></select><button onClick={level}>— LEVEL / ZONE</button><select value={snap} onChange={(event) => setSnap(event.target.value as typeof snap)}><option value="free">Free draw</option><option value="weak">Weak snap</option><option value="strong">Strong snap</option></select><button onClick={undo}>UNDO</button><button onClick={redoAction}>REDO</button><button onClick={reset}>RESET CURRENT SETUP</button></section>{help && <Modal close={() => setHelp(false)}>{helpText}</Modal>}</main>;
}

function ResearchTools({ symbol, actualTrades, candidates, setActualTrades, setCandidates, startResearch, setStatus }: { symbol: string; actualTrades: ActualTrade[]; candidates: Candidate[]; setActualTrades: (items: ActualTrade[]) => void; setCandidates: (items: Candidate[]) => void; startResearch: (mode: "reconstruct_real_trade" | "review_bot_candidate", time: number) => Promise<void>; setStatus: (value: string) => void }) { return <details><summary>RESEARCH TOOLS</summary><p>Secondary only: never use these for blind Batch 1 capture.</p><button onClick={() => void api<ActualTrade[]>(`/actual-trades?symbol=${symbol}`).then(setActualTrades).catch((error) => setStatus(String(error)))}>LOAD REAL TRADES</button>{actualTrades.map((trade) => <button key={trade.trade_id} onClick={() => void startResearch("reconstruct_real_trade", trade.entry_time)}>RECONSTRUCT {trade.trade_id} · {new Date(trade.entry_time).toLocaleString()} · {trade.side}</button>)}<button onClick={() => void api<Candidate[]>(`/bot-candidates?symbol=${symbol}&limit=25`).then(setCandidates).catch((error) => setStatus(String(error)))}>LOAD BOT CANDIDATES</button>{candidates.map((candidate, index) => <button key={`${candidate.decision_time}-${index}`} onClick={() => void startResearch("review_bot_candidate", candidate.decision_time)}>REVIEW {new Date(candidate.decision_time).toLocaleString()} · {candidate.side}</button>)}</details>; }
function Modal({ children, close }: { children: React.ReactNode; close: () => void }) { return <div className="modal"><section><button className="close" onClick={close}>×</button><h2>HELP</h2>{children}</section></div>; }
function Tutorial({ step, next }: { step: number; next: () => void }) { const text = ["This is a blind historical replay. Everything after the current replay point is hidden. Trade as if the market were live.", "Use 4H, 1H and 15M exactly as you normally do.", "Draw the triangles and levels that genuinely influence your decision.", "If you would trade, choose Long or Short and position Entry, Stop and Target.", "Press Record. The workstation saves your decision and screenshots automatically."][step]; return <div className="modal"><section><small>{step + 1} / 5</small><p>{text}</p><button className="commit" onClick={next}>{step === 4 ? "START FIRST REPLAY" : "NEXT"}</button></section></div>; }
createRoot(document.getElementById("root")!).render(<App />);
