import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { KLineChartAdapter } from "./charts/KLineChartAdapter";
import type {
  Annotation,
  OverlayLine,
  Point,
  PriceLevel,
  Timeframe,
  TradePlan,
  Triangle,
} from "./types";
import "./style.css";

type Session = {
  session_id: string;
  symbol: string;
  replay_time: number;
  mode: string;
};
type Trade = {
  simulated_trade_id: string;
  status: string;
  realized_r?: number | null;
};
type Candidate = {
  symbol: string;
  decision_time: number;
  side: "long" | "short";
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  [key: string]: unknown;
};
const api = async <T,>(path: string, options?: RequestInit): Promise<T> => {
  const r = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
};
const blank = (s: Session): Annotation => ({
  annotation_id: crypto.randomUUID(),
  session_id: s.session_id,
  symbol: s.symbol,
  decision_time: s.replay_time,
  market_state: "no_structure",
  structures: [],
  levels: [],
  notes: "",
});
const updateLine = (
  xs: Triangle[],
  id: string,
  w: "upper" | "lower",
  line: OverlayLine,
) =>
  xs.map((x) =>
    x.structure_id === id
      ? { ...x, geometry: { ...x.geometry, [`${w}_line`]: line } }
      : x,
  );

function App() {
  const ref = useRef<HTMLDivElement>(null),
    chart = useRef<KLineChartAdapter>();
  const [session, setSession] = useState<Session | null>(null),
    [symbol, setSymbol] = useState("BTC"),
    [tf, setTf] = useState<Timeframe>("15m"),
    [annotation, setAnnotation] = useState<Annotation | null>(null),
    [history, setHistory] = useState<Annotation[]>([]),
    [redo, setRedo] = useState<Annotation[]>([]),
    [snap, setSnap] = useState<"free" | "weak" | "strong">("weak"),
    [role, setRole] = useState<
      "macro_parent" | "local_parent" | "entry" | "other"
    >("entry"),
    [levelKind, setLevelKind] = useState<PriceLevel["kind"]>("strong_level"),
    [status, setStatus] = useState("Choose a market and begin."),
    [trades, setTrades] = useState<Trade[]>([]),
    [candidate, setCandidate] = useState<Candidate | null>(null),
    [candidates, setCandidates] = useState<Candidate[]>([]);
  useEffect(() => {
    if (!ref.current) return;
    chart.current = new KLineChartAdapter(ref.current);
    return () => chart.current?.destroy();
  }, []);
  const change = (f: (a: Annotation) => Annotation) =>
    setAnnotation((a) => {
      if (!a) return a;
      setHistory((h) => [...h, a]);
      setRedo([]);
      return f(a);
    });
  const reload = async (s: Session, timeframe = tf) => {
    const rows = await api<Array<Record<string, number>>>(
      `/sessions/${s.session_id}/candles/${timeframe}`,
    );
    chart.current?.setCandles(
      rows.map((c) => ({
        timestamp: c.open_time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
        volume: c.volume,
      })),
    );
    setStatus(
      `${timeframe} · ${rows.length} candles visible · future data blocked`,
    );
  };
  const restore = () => {
    if (!annotation) return;
    chart.current?.restore(
      annotation.structures,
      annotation.levels,
      annotation.trade_plan ?? null,
      annotation.side ?? null,
      (id, w, line) =>
        change((a) => ({
          ...a,
          structures: updateLine(a.structures, id, w, line),
        })),
      (id, p) =>
        change((a) => ({
          ...a,
          levels: a.levels.map((x) =>
            x.level_id === id ? { ...x, start: p } : x,
          ),
        })),
      (key, price) =>
        change((a) => ({
          ...a,
          trade_plan: a.trade_plan
            ? { ...a.trade_plan, [key]: price }
            : a.trade_plan,
        })),
    );
  };
  useEffect(restore, [annotation, tf]);
  const load = async (s: Session) => {
    const annotations = await api<Annotation[]>(
      `/sessions/${s.session_id}/annotations`,
    );
    setAnnotation(annotations.at(-1) ?? blank(s));
    setTrades(await api<Trade[]>(`/sessions/${s.session_id}/trades`));
  };
  const start = async (mode = "free_replay", at?: number) => {
    try {
      const markets =
          await api<
            Array<{ symbol: string; timeframe: string; start_time: number }>
          >("/markets"),
        m = markets.find((x) => x.symbol === symbol && x.timeframe === "15m");
      if (!m) return setStatus(`No approved local 15m ${symbol} data.`);
      const s = await api<Session>("/sessions", {
        method: "POST",
        body: JSON.stringify({ symbol, start_time: at ?? m.start_time, mode }),
      });
      setSession(s);
      localStorage.setItem("annotator-session", s.session_id);
      setAnnotation(blank(s));
      setHistory([]);
      await reload(s);
    } catch (e) {
      setStatus(String(e));
    }
  };
  useEffect(() => {
    const id = localStorage.getItem("annotator-session");
    if (id)
      api<Session>(`/sessions/${id}`)
        .then(async (s) => {
          setSession(s);
          setSymbol(s.symbol);
          await reload(s);
          await load(s);
        })
        .catch(() => localStorage.removeItem("annotator-session"));
  }, []);
  const advance = async (n = 1) => {
    if (!session) return;
    const s = await api<Session>(`/sessions/${session.session_id}/advance`, {
      method: "POST",
      body: JSON.stringify({ count: n }),
    });
    setSession(s);
    setAnnotation((a) => (a ? { ...a, decision_time: s.replay_time } : a));
    await reload(s);
    setTrades(await api<Trade[]>(`/sessions/${s.session_id}/trades`));
  };
  const triangle = () => {
    if (!annotation) return;
    chart.current?.drawSegment("upper", snap, (upper) =>
      chart.current?.drawSegment("lower", snap, (lower) =>
        change((a) => ({
          ...a,
          structures: [
            ...a.structures,
            {
              structure_id: crypto.randomUUID(),
              timeframe: tf,
              role,
              geometry: {
                upper_line: upper,
                lower_line: lower,
                snap_mode: snap,
              },
            },
          ],
        })),
      ),
    );
  };
  const level = () =>
    chart.current?.drawHorizontal("level", snap, (p) =>
      change((a) => ({
        ...a,
        levels: [
          ...a.levels,
          {
            level_id: crypto.randomUUID(),
            timeframe: tf,
            kind: levelKind,
            start: p,
          },
        ],
      })),
    );
  const plan = (key: keyof TradePlan) =>
    chart.current?.drawHorizontal(key, snap, (p) =>
      change((a) => ({
        ...a,
        trade_plan: {
          entry_price: a.trade_plan?.entry_price ?? p.price,
          stop_loss: a.trade_plan?.stop_loss ?? p.price,
          take_profit: a.trade_plan?.take_profit ?? p.price,
          [key]: p.price,
        },
      })),
    );
  const undo = () => {
    const p = history.at(-1);
    if (p) {
      setHistory((h) => h.slice(0, -1));
      if (annotation) setRedo((r) => [...r, annotation]);
      setAnnotation(p);
    }
  };
  const redoAction = () => {
    const n = redo.at(-1);
    if (n) {
      setRedo((r) => r.slice(0, -1));
      if (annotation) setHistory((h) => [...h, annotation]);
      setAnnotation(n);
    }
  };
  const save = async () => {
    if (!annotation || !session) return;
    try {
      const saved = await api<Annotation>("/annotations", {
        method: "POST",
        body: JSON.stringify({
          ...annotation,
          decision_time: session.replay_time,
        }),
      });
      setAnnotation(saved);
      for (const timeframe of ["4h", "1h", "15m"] as Timeframe[]) {
        await reload(session, timeframe);
        await new Promise((r) => setTimeout(r, 120));
        const image = chart.current?.snapshot();
        if (image)
          await api(`/annotations/${saved.annotation_id}/screenshots`, {
            method: "POST",
            body: JSON.stringify({ timeframe, image_data_url: image }),
          });
      }
      await reload(session, tf);
      setStatus("Annotation and three chart screenshots saved.");
    } catch (e) {
      setStatus(String(e));
    }
  };
  const place = async () => {
    if (!annotation?.trade_plan || !annotation.side || !session)
      return setStatus("Set direction and plan first.");
    await save();
    const p = annotation.trade_plan,
      t = await api<Trade>("/trades", {
        method: "POST",
        body: JSON.stringify({
          annotation_id: annotation.annotation_id,
          session_id: session.session_id,
          symbol: session.symbol,
          side: annotation.side,
          entry_price: p.entry_price,
          stop_loss: p.stop_loss,
          take_profit: p.take_profit,
          created_at_market_time: session.replay_time,
        }),
      });
    setTrades((x) => [...x, t]);
    setStatus("Trade placed. Its outcome is hidden until replay advances.");
  };
  const manualExit = async (trade: Trade) => {
    if (!session) return;
    const value = window.prompt("Manual exit price");
    if (!value) return;
    await api(`/trades/${trade.simulated_trade_id}/manual-exit`, {
      method: "POST",
      body: JSON.stringify({
        price: Number(value),
        timestamp: session.replay_time,
      }),
    });
    setTrades(await api<Trade[]>(`/sessions/${session.session_id}/trades`));
  };
  const reconstruct = async () => {
    const xs = await api<Array<{ entry_time: number }>>(
      `/actual-trades?symbol=${symbol}`,
    );
    if (!xs.length)
      return setStatus("Import actual_trades.csv through the local API first.");
    await start("reconstruct_real_trade", xs[0].entry_time);
  };
  const bot = async () => {
    const xs = await api<Candidate[]>(`/bot-candidates?symbol=${symbol}`);
    setCandidates(xs);
    setStatus(`${xs.length} baseline candidates available for review.`);
  };
  const selectCandidate = async (c: Candidate) => {
    setCandidate(c);
    await start("review_bot_candidate", c.decision_time);
  };
  const verdict = async (v: string) => {
    if (!candidate || !annotation) return;
    await save();
    await api("/bot-reviews", {
      method: "POST",
      body: JSON.stringify({
        annotation_id: annotation.annotation_id,
        candidate,
        verdict: v,
      }),
    });
    setStatus(`Candidate marked ${v}; bot and human geometry stay separate.`);
  };
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if (
        e.target instanceof HTMLInputElement ||
        e.target instanceof HTMLSelectElement ||
        e.target instanceof HTMLTextAreaElement
      )
        return;
      if (e.key === "ArrowRight") advance(e.shiftKey ? 5 : 1);
      if (e.key.toLowerCase() === "t") triangle();
      if (e.key.toLowerCase() === "h") level();
      if (e.key.toLowerCase() === "e") plan("entry_price");
      if (e.key.toLowerCase() === "s") plan("stop_loss");
      if (e.key.toLowerCase() === "p") plan("take_profit");
      if (e.metaKey && e.key === "z") undo();
      if (["1", "2", "3", "4", "5"].includes(e.key))
        change((a) => ({ ...a, confidence: Number(e.key) }));
    };
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  });
  const metrics = useMemo(
    () =>
      annotation?.trade_plan
        ? {
            risk: Math.abs(
              annotation.trade_plan.entry_price -
                annotation.trade_plan.stop_loss,
            ),
            reward: Math.abs(
              annotation.trade_plan.take_profit -
                annotation.trade_plan.entry_price,
            ),
          }
        : null,
    [annotation],
  );
  return (
    <main>
      <header>
        <div className="brand">
          REPLAY <i>01</i>
        </div>
        <div className="live">LOCAL · NO FUTURE DATA</div>
        <select value={symbol} onChange={(e) => setSymbol(e.target.value)}>
          <option>BTC</option>
          <option>ETH</option>
          <option>SOL</option>
        </select>
        <button onClick={() => start()}>NEW REPLAY</button>
        <button onClick={reconstruct}>RECONSTRUCT</button>
        <button onClick={bot}>BOT REVIEW</button>
      </header>
      <section className="toolbar">
        {(["4h", "1h", "15m"] as Timeframe[]).map((x) => (
          <button
            key={x}
            className={tf === x ? "active" : ""}
            onClick={() => {
              setTf(x);
              if (session) reload(session, x);
            }}
          >
            {x}
          </button>
        ))}
        <select
          value={snap}
          onChange={(e) => setSnap(e.target.value as typeof snap)}
        >
          <option value="free">free draw</option>
          <option value="weak">weak snap</option>
          <option value="strong">strong snap</option>
        </select>
        <span>
          {session
            ? new Date(session.replay_time).toLocaleString()
            : "No session"}
        </span>
        <button onClick={() => advance(1)}>NEXT →</button>
        <button onClick={() => advance(5)}>+5</button>
        <button onClick={undo}>UNDO</button>
        <button onClick={redoAction}>REDO</button>
      </section>
      <section className="workspace">
        <div className="chart">
          <div ref={ref} className="chart-canvas" />
          <p>{status}</p>
        </div>
        <aside>
          <h2>HUMAN CALL</h2>
          <label>
            Market state
            <select
              value={annotation?.market_state ?? "no_structure"}
              onChange={(e) =>
                change((a) => ({
                  ...a,
                  market_state: e.target.value as Annotation["market_state"],
                }))
              }
            >
              <option value="no_structure">NO STRUCTURE</option>
              <option value="valid_triangle_no_trade">
                VALID TRIANGLE / NO TRADE
              </option>
              <option value="maybe_setup">MAYBE SETUP</option>
              <option value="trade">TRADE</option>
            </select>
          </label>
          <div className="direction">
            <button
              className={annotation?.side === "long" ? "selected" : ""}
              onClick={() => change((a) => ({ ...a, side: "long" }))}
            >
              LONG
            </button>
            <button
              className={annotation?.side === "short" ? "selected" : ""}
              onClick={() => change((a) => ({ ...a, side: "short" }))}
            >
              SHORT
            </button>
          </div>
          <label>
            Confidence
            <select
              value={annotation?.confidence ?? ""}
              onChange={(e) =>
                change((a) => ({
                  ...a,
                  confidence: e.target.value ? Number(e.target.value) : null,
                }))
              }
            >
              <option value="">—</option>
              {[1, 2, 3, 4, 5].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          <div className="tools">
            <select
              value={role}
              onChange={(e) => setRole(e.target.value as typeof role)}
            >
              <option value="macro_parent">macro parent</option>
              <option value="local_parent">local parent</option>
              <option value="entry">entry</option>
              <option value="other">other</option>
            </select>
            <button onClick={triangle}>T TRIANGLE</button>
            <select
              value={levelKind}
              onChange={(e) =>
                setLevelKind(e.target.value as PriceLevel["kind"])
              }
            >
              <option value="strong_level">strong level</option>
              <option value="support">support</option>
              <option value="resistance">resistance</option>
              <option value="strong_zone">strong zone</option>
            </select>
            <button onClick={level}>H LEVEL</button>
          </div>
          <div className="saved">
            {annotation?.structures.map((x) => (
              <div key={x.structure_id}>
                △ {x.timeframe}
                <button
                  onClick={() =>
                    change((a) => ({
                      ...a,
                      structures: a.structures.filter(
                        (y) => y.structure_id !== x.structure_id,
                      ),
                    }))
                  }
                >
                  ×
                </button>
              </div>
            ))}
            {annotation?.levels.map((x) => (
              <div key={x.level_id}>
                — {x.kind}
                <button
                  onClick={() =>
                    change((a) => ({
                      ...a,
                      levels: a.levels.filter((y) => y.level_id !== x.level_id),
                    }))
                  }
                >
                  ×
                </button>
              </div>
            ))}
          </div>
          <h3>TRADE PLAN</h3>
          {(["entry_price", "stop_loss", "take_profit"] as const).map((k) => (
            <label key={k}>
              {k.replace("_", " ").toUpperCase()}
              <div className="plan-input">
                <input
                  type="number"
                  value={annotation?.trade_plan?.[k] ?? ""}
                  onChange={(e) =>
                    change((a) => ({
                      ...a,
                      trade_plan: {
                        entry_price: a.trade_plan?.entry_price ?? 0,
                        stop_loss: a.trade_plan?.stop_loss ?? 0,
                        take_profit: a.trade_plan?.take_profit ?? 0,
                        [k]: Number(e.target.value),
                      },
                    }))
                  }
                />
                <button onClick={() => plan(k)}>DRAW</button>
              </div>
            </label>
          ))}
          {metrics && (
            <small>
              Risk {metrics.risk.toFixed(2)} · Reward{" "}
              {metrics.reward.toFixed(2)} · R:R{" "}
              {(metrics.reward / metrics.risk).toFixed(2)}
            </small>
          )}
          <label>
            Notes
            <textarea
              value={annotation?.notes ?? ""}
              onChange={(e) => change((a) => ({ ...a, notes: e.target.value }))}
            />
          </label>
          <button className="commit" onClick={save}>
            SAVE ANNOTATION
          </button>
          <button className="commit" onClick={place}>
            PLACE SIMULATED TRADE
          </button>
          {trades.map((t) => (
            <div key={t.simulated_trade_id}>
              <small>
                Trade: {t.status}
                {t.realized_r !== null && t.realized_r !== undefined
                  ? ` · ${t.realized_r.toFixed(2)}R`
                  : ""}
              </small>
              {t.status === "open" && (
                <button onClick={() => manualExit(t)}>MANUAL EXIT</button>
              )}
            </div>
          ))}
          {candidate && (
            <div className="review">
              <b>BOT CANDIDATE</b>
              <button onClick={() => verdict("correct")}>CORRECT</button>
              <button onClick={() => verdict("wrong")}>WRONG</button>
              <button onClick={() => verdict("close_but_redraw")}>
                REDRAW
              </button>
            </div>
          )}
          {candidates.length > 0 && (
            <select
              onChange={(e) => {
                const x = candidates[Number(e.target.value)];
                if (x) selectCandidate(x);
              }}
            >
              <option>select candidate</option>
              {candidates.map((x, i) => (
                <option key={x.decision_time} value={i}>
                  {new Date(x.decision_time).toLocaleString()} · {x.side}
                </option>
              ))}
            </select>
          )}
          <small>
            → next · Shift+→ +5 · T triangle · H level · E/S/P plan · ⌘Z undo
          </small>
        </aside>
      </section>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<App />);
