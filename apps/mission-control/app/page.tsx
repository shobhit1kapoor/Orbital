"use client";

import {
  Activity,
  BadgeCheck,
  Binary,
  Blocks,
  ChevronRight,
  CircleAlert,
  FileKey,
  Gauge,
  GitBranch,
  Orbit,
  Play,
  Radar,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { motion } from "framer-motion";
import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";

type Screen = "launch" | "evidence" | "replay" | "causal" | "frontier" | "safety" | "certificate";
type Json = Record<string, unknown>;

interface Snapshot {
  generatedAt: string;
  connected: boolean;
  summary: { campaigns?: Json[]; certificates?: Json[]; rollout?: Json } | null;
  parity: { confirmed?: number; contradicted?: number; score?: number | null } | null;
  runtime: { rollout?: Json; attestations?: Json[]; rollbacks?: Json[] } | null;
  findings: Json[];
  frontier: Json[];
}

const navigation: Array<{ id: Screen; label: string; icon: typeof Orbit }> = [
  { id: "launch", label: "Launch Console", icon: Gauge },
  { id: "evidence", label: "Evidence Parity", icon: Radar },
  { id: "replay", label: "Replay Theater", icon: Play },
  { id: "causal", label: "Causal Graph", icon: GitBranch },
  { id: "frontier", label: "Authority Frontier", icon: Activity },
  { id: "safety", label: "Safety Case", icon: ShieldCheck },
  { id: "certificate", label: "Certificate", icon: FileKey },
];

function useSnapshot() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const refresh = async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/snapshot", { cache: "no-store" });
      setSnapshot(await response.json());
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    const initialRefresh = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      window.clearTimeout(initialRefresh);
      window.clearInterval(timer);
    };
  }, []);
  return { snapshot, loading, refresh };
}

function Metric({ label, value, tone = "cyan" }: { label: string; value: string; tone?: "cyan" | "amber" | "red" | "orange" }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong className={`tone-${tone}`}>{value}</strong>
    </div>
  );
}

function Empty({ title }: { title: string }) {
  return (
    <div className="empty-state">
      <Orbit size={28} />
      <strong>{title}</strong>
      <span>Awaiting verified telemetry from the ORBITAL control plane.</span>
    </div>
  );
}

function LaunchConsole({ snapshot }: { snapshot: Snapshot | null }) {
  const certificate = snapshot?.summary?.certificates?.[0] as Json | undefined;
  const campaign = snapshot?.summary?.campaigns?.[0] as Json | undefined;
  const verdict = String(certificate?.verdict ?? "UNKNOWN");
  const parity = snapshot?.parity?.score;
  return (
    <section className="screen launch-grid">
      <div className="hero-card span-2">
        <div>
          <div className="eyebrow">REFUND AGENT V2.1 · FLIGHT READINESS</div>
          <h2 className={`verdict verdict-${verdict.toLowerCase().replaceAll("-", "")}`}>{verdict}</h2>
          <p>Every autonomous agent must earn—and continuously retain—the authority to act.</p>
        </div>
        <div className="orbital-mark"><Orbit size={64} /></div>
      </div>
      <div className="panel metrics-panel">
        <div className="panel-title"><Activity size={16} /> Evidence summary</div>
        <Metric label="Campaign status" value={String(campaign?.status ?? "NOT STARTED")} tone="orange" />
        <Metric label="Evidence parity" value={parity == null ? "—" : `${(parity * 100).toFixed(1)}%`} />
        <Metric label="Mission coverage" value={certificate ? `${Number(certificate.mission_coverage ?? 0) * 100}%` : "—"} />
        <Metric label="Replay fidelity" value={certificate ? `${Number(certificate.replay_fidelity ?? 0) * 100}%` : "—"} />
      </div>
      <div className="panel blocker-panel">
        <div className="panel-title"><CircleAlert size={16} /> Primary blocker</div>
        <h3>{verdict === "UNKNOWN" ? "Required evidence has not been certified." : "Certificate restrictions are active."}</h3>
        <p>Open supporting traces in SigNoz to inspect semantic, policy, OBI, and receipt evidence.</p>
        <button className="button">Open SigNoz evidence <ChevronRight size={16} /></button>
      </div>
      <div className="panel span-2 chart-panel">
        <div className="panel-title"><Binary size={16} /> Candidate comparison</div>
        <ResponsiveContainer width="100%" height={190}>
          <AreaChart data={(snapshot?.summary?.campaigns ?? []).map((item, index) => ({ index, runs: Number(item.live_runs ?? 0) + Number(item.generated_runs ?? 0) }))}>
            <defs><linearGradient id="orange" x1="0" y1="0" x2="0" y2="1"><stop offset="5%" stopColor="#ff6b2c" stopOpacity={0.5}/><stop offset="95%" stopColor="#ff6b2c" stopOpacity={0}/></linearGradient></defs>
            <CartesianGrid stroke="#182439" vertical={false} />
            <XAxis dataKey="index" stroke="#61708a" />
            <YAxis stroke="#61708a" />
            <Tooltip contentStyle={{ background: "#0b1321", border: "1px solid #22314a" }} />
            <Area type="monotone" dataKey="runs" stroke="#ff6b2c" fill="url(#orange)" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
}

function EvidenceParity({ snapshot }: { snapshot: Snapshot | null }) {
  const parity = snapshot?.parity;
  const rows = [
    ["Agent SDK", "action.propose", parity?.contradicted ? "store_credit" : "issue_refund", parity?.contradicted ? "mismatch" : "confirmed"],
    ["OPA", "policy.authorize", parity?.contradicted ? "absent" : "allow", parity?.contradicted ? "mismatch" : "confirmed"],
    ["OBI", "network.client", "POST /refunds", "observed"],
    ["Tool receipt", "effect.verify", parity?.confirmed ? "signature valid" : "awaiting", parity?.confirmed ? "confirmed" : "unknown"],
  ];
  return (
    <section className="screen">
      <div className="section-heading"><div><span className="eyebrow">PARALLAX</span><h2>Evidence Parity</h2></div><Metric label="Parity score" value={parity?.score == null ? "—" : `${(parity.score * 100).toFixed(1)}%`} /></div>
      <div className="timeline-grid">
        <div className="timeline-header">EVIDENCE PLANE</div><div className="timeline-header">CLAIM</div><div className="timeline-header">OBSERVATION</div><div className="timeline-header">STATE</div>
        {rows.map(([plane, claim, observation, state], index) => (
          <motion.div className="timeline-row contents" key={plane} initial={{ opacity: 0, x: -12 }} animate={{ opacity: 1, x: 0 }} transition={{ delay: index * 0.08 }}>
            <div>{plane}</div><div className="mono">{claim}</div><div className="mono">{observation}</div><div><span className={`state state-${state}`}>{state}</span></div>
          </motion.div>
        ))}
      </div>
    </section>
  );
}

function ReplayTheater({ snapshot }: { snapshot: Snapshot | null }) {
  const phases = ["Mission", "Retrieval", "Model", "Propose", "Authorize", "Commit", "Verify"];
  return (
    <section className="screen">
      <div className="section-heading"><div><span className="eyebrow">CAPSULE · RANGE</span><h2>Replay Theater</h2></div><button className="button"><Play size={15}/> Run selected branch</button></div>
      <div className="replay-stack">
        {["Original production mission", "Candidate replay", "Counterfactual correction"].map((lane, laneIndex) => (
          <div className="replay-lane" key={lane}>
            <div className="lane-label">{lane}</div>
            <div className="trace-path">
              {phases.map((phase, index) => <motion.div key={phase} className={`trace-node lane-${laneIndex}`} initial={{ scale: 0.6, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={{ delay: index * 0.06 }}><span>{index + 1}</span>{phase}</motion.div>)}
            </div>
          </div>
        ))}
      </div>
      {!snapshot?.summary?.campaigns?.length && <Empty title="No replay campaign selected" />}
    </section>
  );
}

function CausalGraph({ snapshot }: { snapshot: Snapshot | null }) {
  const finding = snapshot?.findings?.[0] as { contributions?: Array<{ factor: string; contribution: number }> } | undefined;
  const contributions = finding?.contributions ?? [];
  const nodes: Node[] = contributions.map((item, index) => ({ id: item.factor, position: { x: 40 + index * 185, y: 80 + (index % 2) * 120 }, data: { label: `${item.factor.replaceAll("_", " ")} · ${(item.contribution * 100).toFixed(0)}%` }, className: "causal-node" }));
  nodes.push({ id: "failure", position: { x: 780, y: 180 }, data: { label: "Unsafe refund" }, className: "causal-node danger-node" });
  const edges: Edge[] = contributions.map((item) => ({ id: `${item.factor}-failure`, source: item.factor, target: "failure", animated: true, style: { stroke: "#ff6b2c", strokeWidth: Math.max(1, item.contribution * 8) } }));
  return (
    <section className="screen graph-screen">
      <div className="section-heading"><div><span className="eyebrow">FORK</span><h2>Counterfactual Causal Graph</h2></div><span className="pill">128 SHAPLEY PERMUTATIONS</span></div>
      {contributions.length ? <div className="flow-wrap"><ReactFlow nodes={nodes} edges={edges} fitView><Background color="#22314a" gap={22}/><Controls/></ReactFlow></div> : <Empty title="No causal finding generated" />}
    </section>
  );
}

function AuthorityFrontier({ snapshot }: { snapshot: Snapshot | null }) {
  const data = (snapshot?.frontier ?? []).map((point, index) => ({ level: index, completion: Number(point.verified_completion ?? 0) * 100, efficiency: Number(point.authority_efficiency ?? 0) * 100 }));
  return (
    <section className="screen">
      <div className="section-heading"><div><span className="eyebrow">FRONTIER</span><h2>Autonomous Authority Measurement</h2></div><span className="pill">LEVELS 0—5</span></div>
      {data.length ? <div className="panel frontier-chart"><ResponsiveContainer width="100%" height={420}><LineChart data={data}><CartesianGrid stroke="#182439"/><XAxis dataKey="level" stroke="#61708a"/><YAxis stroke="#61708a" domain={[0,100]}/><Tooltip contentStyle={{background:"#0b1321",border:"1px solid #22314a"}}/><Line dataKey="completion" stroke="#42d7e6" strokeWidth={3}/><Line dataKey="efficiency" stroke="#ff6b2c" strokeWidth={3}/></LineChart></ResponsiveContainer></div> : <Empty title="Authority campaign has not run" />}
    </section>
  );
}

function SafetyCase({ snapshot }: { snapshot: Snapshot | null }) {
  const certificate = snapshot?.summary?.certificates?.[0] as { safety_case?: { nodes?: Array<{ node_id: string; kind: string; text: string }> } } | undefined;
  const nodes = certificate?.safety_case?.nodes ?? [];
  return (
    <section className="screen">
      <div className="section-heading"><div><span className="eyebrow">CLEARANCE</span><h2>Structured Safety Case</h2></div><BadgeCheck className="tone-cyan"/></div>
      {nodes.length ? <div className="safety-tree">{nodes.map((node) => <div key={node.node_id} className={`safety-node safety-${node.kind}`}><span>{node.kind.replaceAll("_", " ")}</span><strong>{node.text}</strong></div>)}</div> : <Empty title="No safety case issued" />}
    </section>
  );
}

function CertificateScreen({ snapshot }: { snapshot: Snapshot | null }) {
  const certificate = snapshot?.summary?.certificates?.[0] as Json | undefined;
  if (!certificate) return <section className="screen"><Empty title="No flight certificate issued" /></section>;
  return (
    <section className="screen certificate-wrap">
      <div className="certificate-card">
        <div className="certificate-seal"><Orbit size={44}/><span>ORBITAL Σ</span></div>
        <span className="eyebrow">SIGNED FLIGHT AUTHORITY</span>
        <h2>{String(certificate.verdict)}</h2>
        <p className="certificate-id mono">{String(certificate.certificate_id)}</p>
        <div className="certificate-grid">
          <Metric label="Candidate" value={String(certificate.candidate_id)} />
          <Metric label="Granted authority" value={String(certificate.granted_authority)} tone="orange" />
          <Metric label="Maximum refund" value={`$${Number(certificate.maximum_refund_usd).toFixed(2)}`} />
          <Metric label="Canary traffic" value={`${Number(certificate.canary_percentage)}%`} />
        </div>
        <div className="signature-block"><span>Cryptographic signature</span><code>{String(certificate.signature).slice(0, 64)}…</code></div>
      </div>
    </section>
  );
}

export default function Home() {
  const [screen, setScreen] = useState<Screen>("launch");
  const { snapshot, loading, refresh } = useSnapshot();
  const active = useMemo(() => navigation.find((item) => item.id === screen), [screen]);
  const screens: Record<Screen, React.ReactNode> = {
    launch: <LaunchConsole snapshot={snapshot}/>, evidence: <EvidenceParity snapshot={snapshot}/>, replay: <ReplayTheater snapshot={snapshot}/>, causal: <CausalGraph snapshot={snapshot}/>, frontier: <AuthorityFrontier snapshot={snapshot}/>, safety: <SafetyCase snapshot={snapshot}/>, certificate: <CertificateScreen snapshot={snapshot}/>,
  };
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand"><div className="brand-icon"><Orbit/></div><div><strong>ORBITAL <em>Σ</em></strong><span>MISSION CONTROL</span></div></div>
        <nav>{navigation.map((item) => <button key={item.id} onClick={() => setScreen(item.id)} className={screen === item.id ? "active" : ""}><item.icon size={17}/><span>{item.label}</span>{screen === item.id && <ChevronRight size={15}/>}</button>)}</nav>
        <div className="sidebar-footer"><div className={`connection ${snapshot?.connected ? "online" : "offline"}`}><span/>{snapshot?.connected ? "EVIDENCE PLANE ONLINE" : "EVIDENCE PLANE OFFLINE"}</div><small>FLIGHT ASSURANCE v0.1.0</small></div>
      </aside>
      <div className="main-column">
        <header><div><span className="breadcrumb">ORBITAL Σ / {active?.label.toUpperCase()}</span><h1>{active?.label}</h1></div><div className="header-actions"><span>{snapshot ? new Date(snapshot.generatedAt).toLocaleTimeString() : "—"}</span><button aria-label="Refresh telemetry" onClick={() => void refresh()} className={loading ? "spinning" : ""}><RefreshCw size={17}/></button><span className="pill"><Blocks size={13}/> LIVE EVIDENCE</span></div></header>
        <motion.div key={screen} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>{screens[screen]}</motion.div>
      </div>
    </main>
  );
}
