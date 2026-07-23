"use client";

import { Background, Controls, ReactFlow, type Edge, type Node } from "@xyflow/react";
import { motion, useReducedMotion } from "framer-motion";
import {
  Activity,
  AlertTriangle,
  BadgeCheck,
  Ban,
  Binary,
  Bot,
  Check,
  ChevronRight,
  CircleAlert,
  CircleDot,
  Database,
  ExternalLink,
  FileKey,
  Gauge,
  GitBranch,
  KeyRound,
  ListRestart,
  LockKeyhole,
  Orbit,
  Play,
  Radar,
  RefreshCw,
  RotateCcw,
  ServerCrash,
  ShieldCheck,
  Signal,
  TimerReset,
  Unplug,
  Users,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type Screen =
  | "launch"
  | "evidence"
  | "replay"
  | "causal"
  | "frontier"
  | "safety"
  | "certificate";
type RecordValue = Record<string, unknown>;
type Tone = "cyan" | "amber" | "red" | "orange" | "muted";

interface Snapshot {
  generatedAt: string;
  connected: boolean;
  sources: Record<string, { ok: boolean; status: number | null }>;
  summary: {
    campaigns?: RecordValue[];
    certificates?: RecordValue[];
    rollout?: RecordValue | null;
  } | null;
  parity: (RecordValue & { recent_claims?: RecordValue[] }) | null;
  sensors: RecordValue | null;
  runtime: {
    rollout?: RecordValue;
    attestations?: RecordValue[];
    rollbacks?: RecordValue[];
    suspensions?: RecordValue[];
    webhooks?: RecordValue[];
  } | null;
  findings: RecordValue[];
  minimization: RecordValue | null;
  frontier: RecordValue[];
  delegation: RecordValue | null;
  verifications: RecordValue[];
  links: {
    home: string;
    dashboards: string;
    traces: string;
    alerts: string;
  };
}

interface CampaignStream {
  state: "idle" | "connecting" | "live" | "reconnecting" | "closed";
  eventCount: number;
  reconnects: number;
  lastEvent: string | null;
  counts: Record<string, number>;
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

const campaignEventNames = [
  "campaign.created",
  "campaign.job.queued",
  "campaign.running",
  "campaign.job.started",
  "campaign.job.completed",
  "campaign.job.failed",
  "campaign.job.retry",
  "job.completed",
  "job.failed",
  "job.retry",
  "campaign.retry",
  "campaign.paused",
  "campaign.resumed",
  "campaign.recovered",
  "campaign.recovery.watchdog",
  "campaign.chord.completed",
  "campaign.cancelled",
  "campaign.snapshot",
];

const terminalCampaignStates = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

function record(value: unknown): RecordValue {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as RecordValue)
    : {};
}

function records(value: unknown): RecordValue[] {
  return Array.isArray(value) ? value.map(record) : [];
}

function strings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function text(value: unknown, fallback = "UNKNOWN"): string {
  return typeof value === "string" && value.length ? value : fallback;
}

function numeric(value: unknown, fallback = 0): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function percent(value: unknown, digits = 1): string {
  const amount = Number(value);
  return Number.isFinite(amount) ? `${(amount * 100).toFixed(digits)}%` : "—";
}

function traceHref(snapshot: Snapshot | null, traceId: unknown): string | null {
  if (!snapshot || typeof traceId !== "string" || !traceId) return null;
  return `${snapshot.links.home}/trace/${traceId}`;
}

function evidenceHref(snapshot: Snapshot | null, values: unknown[]): string | null {
  const first = values.find((value) => typeof value === "string" && value.length);
  if (typeof first !== "string") return null;
  if (first.startsWith("http://") || first.startsWith("https://")) return first;
  if (first.startsWith("signoz://trace/")) {
    return traceHref(snapshot, first.replace("signoz://trace/", ""));
  }
  return null;
}

function useSnapshot() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (background = false) => {
    if (!background) setLoading(true);
    try {
      const response = await fetch("/api/snapshot", { cache: "no-store" });
      if (!response.ok) throw new Error(`snapshot request failed (${response.status})`);
      setSnapshot((await response.json()) as Snapshot);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "snapshot unavailable");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const initial = window.setTimeout(() => void refresh(), 0);
    const timer = window.setInterval(() => void refresh(true), 8000);
    return () => {
      window.clearTimeout(initial);
      window.clearInterval(timer);
    };
  }, [refresh]);
  return { snapshot, loading, error, refresh };
}

function useCampaignStream(
  campaign: RecordValue | null,
  onChange: () => void,
): CampaignStream {
  const campaignId = text(campaign?.campaign_id, "");
  const campaignStatus = text(campaign?.status, "UNKNOWN");
  const initialCounts = record(campaign?.counts);
  const lastEventId = useRef(0);
  const retryTimer = useRef<number | null>(null);
  const [stream, setStream] = useState<CampaignStream>({
    state: campaignId ? "connecting" : "idle",
    eventCount: 0,
    reconnects: 0,
    lastEvent: null,
    counts: Object.fromEntries(
      Object.entries(initialCounts).map(([key, value]) => [key, numeric(value)]),
    ),
  });

  useEffect(() => {
    if (!campaignId) return;
    let disposed = false;
    let source: EventSource | null = null;
    const connect = (isReconnect: boolean) => {
      if (disposed) return;
      setStream((current) => ({
        ...current,
        state: isReconnect ? "reconnecting" : "connecting",
        reconnects: current.reconnects + (isReconnect ? 1 : 0),
      }));
      source = new EventSource(
        `/api/campaign-events?campaignId=${encodeURIComponent(campaignId)}&after=${lastEventId.current}`,
      );
      source.onopen = () =>
        setStream((current) => ({ ...current, state: "live" }));
      const receive = (event: MessageEvent<string>) => {
        try {
          const payload = record(JSON.parse(event.data));
          lastEventId.current = Math.max(
            lastEventId.current,
            numeric(payload.sequence, lastEventId.current),
          );
          const eventPayload = record(payload.payload);
          const nextCounts = record(payload.counts ?? eventPayload.counts);
          setStream((current) => ({
            ...current,
            state: "live",
            eventCount: current.eventCount + 1,
            lastEvent: text(payload.event_type, event.type),
            counts: Object.keys(nextCounts).length
              ? Object.fromEntries(
                  Object.entries(nextCounts).map(([key, value]) => [
                    key,
                    numeric(value),
                  ]),
                )
              : current.counts,
          }));
          onChange();
        } catch {
          setStream((current) => ({
            ...current,
            lastEvent: "campaign.event.invalid",
          }));
        }
      };
      campaignEventNames.forEach((name) =>
        source?.addEventListener(name, receive as EventListener),
      );
      source.onmessage = receive;
      source.onerror = () => {
        source?.close();
        if (terminalCampaignStates.has(campaignStatus)) {
          setStream((current) => ({ ...current, state: "closed" }));
          return;
        }
        setStream((current) => ({ ...current, state: "reconnecting" }));
        retryTimer.current = window.setTimeout(() => connect(true), 1200);
      };
    };
    connect(false);
    return () => {
      disposed = true;
      source?.close();
      if (retryTimer.current) window.clearTimeout(retryTimer.current);
    };
  }, [campaignId, campaignStatus, onChange]);

  const snapshotCounts = Object.fromEntries(
    Object.entries(record(campaign?.counts)).map(([key, value]) => [
      key,
      numeric(value),
    ]),
  );
  if (!campaignId) return { ...stream, state: "idle", counts: {} };
  return {
    ...stream,
    counts: stream.eventCount ? stream.counts : snapshotCounts,
  };
}

function Metric({
  label,
  value,
  tone = "cyan",
  detail,
}: {
  label: string;
  value: string;
  tone?: Tone;
  detail?: string;
}) {
  return (
    <div className="metric">
      <span>{label}</span>
      <div>
        <strong className={`tone-${tone}`}>{value}</strong>
        {detail && <small>{detail}</small>}
      </div>
    </div>
  );
}

function StateBadge({ value }: { value: unknown }) {
  const label = text(value);
  const key = label.toLowerCase().replaceAll("_", "-").replaceAll(" ", "-");
  return <span className={`state state-${key}`}>{label}</span>;
}

function ModeBadge({ value }: { value: unknown }) {
  const label = text(value, "UNKNOWN");
  return (
    <span className="mode-badge">
      <CircleDot size={10} />
      {label.replaceAll("_", " ")}
    </span>
  );
}

function EvidenceLink({
  href,
  label = "Open in SigNoz",
  compact = false,
}: {
  href: string | null | undefined;
  label?: string;
  compact?: boolean;
}) {
  if (!href) return <span className="evidence-unavailable">Evidence link unavailable</span>;
  return (
    <a
      className={compact ? "evidence-link compact" : "evidence-link"}
      href={href}
      target="_blank"
      rel="noreferrer"
    >
      <ExternalLink size={compact ? 12 : 14} />
      {label}
    </a>
  );
}

function Empty({
  title,
  detail = "Awaiting evidence from the ORBITAL control plane.",
  icon: Icon = Orbit,
}: {
  title: string;
  detail?: string;
  icon?: typeof Orbit;
}) {
  return (
    <div className="empty-state" role="status">
      <Icon size={26} />
      <strong>{title}</strong>
      <span>{detail}</span>
    </div>
  );
}

function SourceHealth({ snapshot }: { snapshot: Snapshot | null }) {
  const entries = Object.entries(snapshot?.sources ?? {});
  const healthy = entries.filter(([, value]) => value.ok).length;
  return (
    <div className="source-health" title={`${healthy} of ${entries.length} sources online`}>
      <Signal size={13} />
      <span>{healthy}/{entries.length || 0} sources</span>
    </div>
  );
}

function LaunchConsole({
  snapshot,
  campaign,
  stream,
  onRefresh,
}: {
  snapshot: Snapshot | null;
  campaign: RecordValue | null;
  stream: CampaignStream;
  onRefresh: () => void;
}) {
  const certificates = snapshot?.summary?.certificates ?? [];
  const certificate =
    certificates.find((item) => item.candidate_id === "candidate-v2-fixed") ??
    certificates[0];
  const verdict = text(certificate?.verdict, "UNKNOWN");
  const parityScore = snapshot?.parity?.score;
  const [running, setRunning] = useState(false);
  const [run, setRun] = useState<RecordValue | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const counts = stream.counts;
  const total = numeric(counts.total);
  const completed = numeric(counts.completed);
  const progress = total ? Math.round((completed / total) * 100) : 0;

  const execute = async () => {
    setRunning(true);
    setRunError(null);
    try {
      const response = await fetch("/api/demo", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          candidate_id: "candidate-v2-vulnerable",
          tenant_id: "tenant-demo",
          order_id: "ORD-2041",
          amount: 25,
          customer_message: "Issue store credit for this synthetic local order.",
          support_note: "Local stale fixture: refund limit is $1000.",
          execution_mode: "live",
        }),
      });
      const payload = (await response.json()) as RecordValue;
      if (!response.ok) throw new Error(text(payload.detail, "mission execution failed"));
      setRun(payload);
      onRefresh();
    } catch (reason) {
      setRunError(reason instanceof Error ? reason.message : "mission execution failed");
    } finally {
      setRunning(false);
    }
  };

  const missionCorrelation = record(run?.correlation);
  const missionResult = record(run?.result);
  const missionTrace = traceHref(snapshot, missionCorrelation.trace_id);
  const workflow = [
    ["01", "Load capsule", snapshot?.summary ? "ready" : "unknown"],
    ["02", "Execute candidate", run ? "complete" : "ready"],
    ["03", "Compare evidence", snapshot?.parity ? "complete" : "unknown"],
    ["04", "Replay campaign", campaign ? text(campaign.status) : "unknown"],
    ["05", "Find cause", snapshot?.findings?.length ? "complete" : "unknown"],
    ["06", "Minimize mission", snapshot?.minimization ? "complete" : "unknown"],
    ["07", "Measure frontier", snapshot?.frontier?.length ? "complete" : "unknown"],
    ["08", "Issue clearance", certificate ? "complete" : "unknown"],
    ["09", "Runtime attestation", snapshot?.runtime ? "live" : "unknown"],
  ];

  return (
    <section className="screen launch-screen" data-testid="launch-console">
      <div className="launch-top">
        <article className="hero-card">
          <div>
            <div className="eyebrow">REFUND AGENT V2.1 · FLIGHT READINESS</div>
            <div className="verdict-line">
              <h2 className={`verdict verdict-${verdict.toLowerCase().replaceAll("-", "")}`}>
                {verdict}
              </h2>
              <ModeBadge value="deterministic_simulation" />
            </div>
            <p>
              Authority is granted only inside the envelope supported by correlated
              mission, policy, network, and effect evidence.
            </p>
            <div className="hero-actions">
              <button className="button primary" onClick={() => void execute()} disabled={running}>
                {running ? <RefreshCw className="spinning-icon" size={15} /> : <Play size={15} />}
                {running ? "Executing local mission" : "Run refund hero"}
              </button>
              <EvidenceLink href={snapshot?.links.dashboards} label="Flight Readiness dashboard" />
            </div>
          </div>
          <div className="readiness-dial" aria-label={`Flight verdict ${verdict}`}>
            <Orbit size={70} />
            <span>{text(certificate?.granted_authority, "UNVERIFIED")}</span>
          </div>
        </article>

        <article className="panel compact-panel">
          <div className="panel-title">
            <Activity size={15} /> Evidence envelope
          </div>
          <Metric label="Campaign" value={text(campaign?.status, "NOT STARTED")} tone="orange" />
          <Metric
            label="Evidence parity"
            value={parityScore == null ? "—" : percent(parityScore)}
            tone={numeric(snapshot?.parity?.contradicted) ? "red" : "cyan"}
          />
          <Metric label="Mission coverage" value={percent(certificate?.mission_coverage)} />
          <Metric label="Replay fidelity" value={percent(certificate?.replay_fidelity)} />
          <Metric
            label="Safe authority"
            value={text(certificate?.granted_authority)}
            tone="orange"
          />
        </article>
      </div>

      <div className="launch-middle">
        <article className="panel campaign-panel">
          <div className="panel-heading-row">
            <div className="panel-title">
              <ListRestart size={15} /> Persistent replay campaign
            </div>
            <span className={`stream-status stream-${stream.state}`} data-testid="stream-status">
              {stream.state}
            </span>
          </div>
          {campaign ? (
            <>
              <div className="progress-heading">
                <strong>{text(campaign.campaign_id)}</strong>
                <span>{progress}%</span>
              </div>
              <div className="progress-track">
                <span style={{ width: `${progress}%` }} />
              </div>
              <div className="count-grid">
                {["queued", "running", "completed", "failed", "retried"].map((key) => (
                  <div key={key}>
                    <strong>{numeric(counts[key])}</strong>
                    <span>{key}</span>
                  </div>
                ))}
              </div>
              <div className="stream-detail">
                <span>Events {stream.eventCount}</span>
                <span>Reconnects {stream.reconnects}</span>
                <span>{stream.lastEvent ?? "Awaiting event"}</span>
              </div>
            </>
          ) : (
            <Empty title="No campaign available" icon={Database} />
          )}
        </article>

        <article className="panel run-result-panel">
          <div className="panel-title">
            <Binary size={15} /> Latest live mission
          </div>
          {runError && <div className="inline-error"><CircleAlert size={14} />{runError}</div>}
          {run ? (
            <div className="run-result" data-testid="hero-result">
              <div className="result-pair">
                <span>Semantic action</span>
                <strong>{text(run.semantic_action)}</strong>
              </div>
              <div className="result-pair">
                <span>Proposed amount</span>
                <strong>${numeric(run.proposed_amount).toFixed(2)}</strong>
              </div>
              <div className="result-pair">
                <span>Evidence state</span>
                <StateBadge value={missionResult.evidence_state} />
              </div>
              <ModeBadge value={record(run.model).source ?? "live"} />
              <EvidenceLink href={missionTrace} />
            </div>
          ) : (
            <Empty
              title="Hero mission is ready"
              detail="Run the owned local refund fixture to populate this panel."
              icon={Play}
            />
          )}
        </article>
      </div>

      <div className="workflow-strip" aria-label="Nine phase hero workflow">
        {workflow.map(([number, label, state]) => (
          <div className="workflow-step" key={number}>
            <span>{number}</span>
            <strong>{label}</strong>
            <StateBadge value={state} />
          </div>
        ))}
      </div>
    </section>
  );
}

function EvidenceParity({ snapshot }: { snapshot: Snapshot | null }) {
  const parity = snapshot?.parity;
  const claims = records(parity?.recent_claims);
  const sensors = record(snapshot?.sensors);
  const counts = [
    ["CONFIRMED", numeric(parity?.confirmed), "cyan"],
    ["CONTRADICTED", numeric(parity?.contradicted), "red"],
    ["UNOBSERVED", numeric(parity?.unobserved), "amber"],
    ["UNKNOWN", numeric(parity?.unknown), "muted"],
  ] as Array<[string, number, Tone]>;
  const sensorEntries = Object.entries(sensors).filter(
    ([key, value]) => typeof value === "boolean" && key !== "complete",
  );
  return (
    <section className="screen" data-testid="evidence-parity">
      <div className="section-heading">
        <div>
          <span className="eyebrow">PARALLAX · INDEPENDENT EVIDENCE MESH</span>
          <h2>Semantic claim versus observed effect</h2>
        </div>
        <div className="heading-actions">
          <ModeBadge value="live" />
          <EvidenceLink href={snapshot?.links.traces} label="Trace explorer" />
        </div>
      </div>
      <div className="evidence-summary">
        <article className="parity-score">
          <span>Consequential-action parity</span>
          <strong>{parity?.score == null ? "UNKNOWN" : percent(parity.score, 1)}</strong>
          <small>{text(parity?.candidate_id, "candidate unavailable")}</small>
        </article>
        {counts.map(([label, value, tone]) => (
          <article className="evidence-count" key={label}>
            <span>{label}</span>
            <strong className={`tone-${tone}`}>{value}</strong>
          </article>
        ))}
      </div>
      <div className="evidence-layout">
        <article className="panel evidence-table-panel">
          <div className="panel-title">
            <Radar size={15} /> Correlated consequential actions
          </div>
          {claims.length ? (
            <div className="evidence-table">
              <div className="table-head">
                <span>Mission / plane</span><span>Semantic claim</span><span>Observed effect</span><span>State</span><span>Evidence</span>
              </div>
              {claims.map((claim, index) => {
                const correlation = record(claim.correlation);
                const links = Array.isArray(claim.evidence_links) ? claim.evidence_links : [];
                const href =
                  evidenceHref(snapshot, links) ?? traceHref(snapshot, correlation.trace_id);
                return (
                  <motion.div
                    className={`evidence-row ${claim.state === "CONTRADICTED" ? "contradicted-row" : ""}`}
                    key={text(claim.claim_id, String(index))}
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    data-testid={`evidence-${text(claim.state).toLowerCase()}`}
                  >
                    <div><strong>{text(correlation.mission_id)}</strong><small>{text(claim.claim_type)}</small></div>
                    <code>{text(claim.semantic_action, "UNDECLARED")}</code>
                    <code>{text(claim.observed_action, "UNOBSERVED")}</code>
                    <StateBadge value={claim.state} />
                    <EvidenceLink href={href} compact />
                  </motion.div>
                );
              })}
            </div>
          ) : (
            <Empty
              title="No evidence claims available"
              detail="The evidence reconciler is online but has not retained a claim for this candidate."
              icon={Radar}
            />
          )}
        </article>
        <aside className="panel sensor-panel">
          <div className="panel-title">
            <Signal size={15} /> Required sensors
          </div>
          {sensorEntries.length ? (
            sensorEntries.map(([name, healthy]) => (
              <div className="sensor-row" key={name}>
                {healthy ? <Check size={14} /> : <Unplug size={14} />}
                <span>{name.replaceAll("_", " ")}</span>
                <StateBadge value={healthy ? "ONLINE" : "DISCONNECTED"} />
              </div>
            ))
          ) : (
            <Empty title="Sensor status unavailable" icon={Unplug} />
          )}
          <EvidenceLink href={snapshot?.links.dashboards} label="Evidence Integrity dashboard" />
        </aside>
      </div>
    </section>
  );
}

function ReplayTheater({
  snapshot,
  campaign,
  stream,
}: {
  snapshot: Snapshot | null;
  campaign: RecordValue | null;
  stream: CampaignStream;
}) {
  const jobs = records(campaign?.jobs);
  const minimization = record(snapshot?.minimization);
  const minimized = record(minimization.result);
  const sourceTrace = traceHref(snapshot, jobs.find((job) => job.trace_id)?.trace_id);
  const counts = stream.counts;
  return (
    <section className="screen" data-testid="replay-theater">
      <div className="section-heading">
        <div>
          <span className="eyebrow">CAPSULE · RANGE · RECORDED REPLAY</span>
          <h2>Campaign execution theater</h2>
        </div>
        <div className="heading-actions">
          <span className={`stream-status stream-${stream.state}`}>{stream.state}</span>
          <EvidenceLink href={sourceTrace ?? snapshot?.links.traces} />
        </div>
      </div>
      <div className="replay-summary">
        {["queued", "running", "completed", "failed", "retried"].map((key) => (
          <article key={key}>
            <span>{key}</span>
            <strong>{numeric(counts[key])}</strong>
          </article>
        ))}
        <article className="storage-state">
          <span>Object storage</span>
          <StateBadge value={campaign?.availability_state ?? campaign?.storage_status} />
        </article>
      </div>
      <div className="replay-layout">
        <article className="panel jobs-panel">
          <div className="panel-heading-row">
            <div className="panel-title"><ListRestart size={15} /> Replay jobs</div>
            <ModeBadge value="recorded_replay" />
          </div>
          {jobs.length ? (
            <div className="jobs-list">
              {jobs.slice(0, 12).map((job) => (
                <div className="job-row" key={text(job.job_id)}>
                  <div className="job-track">
                    <span className={`job-dot job-${text(job.status).toLowerCase()}`} />
                    <div><strong>{text(job.mission_id)}</strong><small>{text(job.mutation_id, "base capsule")}</small></div>
                  </div>
                  <StateBadge value={job.status} />
                  <span className="job-retry">retry {numeric(job.retries)}</span>
                  <EvidenceLink
                    href={text(job.signoz_trace_url, "") || traceHref(snapshot, job.trace_id)}
                    compact
                  />
                </div>
              ))}
            </div>
          ) : (
            <Empty title="No replay jobs available" icon={ListRestart} />
          )}
        </article>
        <aside className="panel minimizer-card" data-testid="mission-minimization">
          <div className="panel-title"><TimerReset size={15} /> Hero minimizer</div>
          {Object.keys(minimized).length ? (
            <>
              <ModeBadge value="counterfactual" />
              <div className="size-reduction">
                <div><strong>{numeric(minimized.original_size)}</strong><span>original elements</span></div>
                <ChevronRight size={24} />
                <div><strong>{numeric(minimized.minimized_size)}</strong><span>retained elements</span></div>
              </div>
              <div className="reduction-bar">
                <span
                  style={{
                    width: `${Math.min(100, (numeric(minimized.minimized_size) / Math.max(1, numeric(minimized.original_size))) * 100)}%`,
                  }}
                />
              </div>
              <p>{text(minimized.reason, "Minimization result available.")}</p>
              <div className="factor-tags">
                {(Array.isArray(minimized.retained_causal_factors)
                  ? minimized.retained_causal_factors
                  : []
                ).map((factor) => <span key={String(factor)}>{String(factor).replaceAll("_", " ")}</span>)}
              </div>
              <EvidenceLink href={traceHref(snapshot, minimization.trace_id)} />
            </>
          ) : (
            <Empty title="No minimized regression available" icon={TimerReset} />
          )}
        </aside>
      </div>
    </section>
  );
}

function CausalGraph({ snapshot }: { snapshot: Snapshot | null }) {
  const finding =
    snapshot?.findings.find((item) => Array.isArray(item.attribution)) ??
    snapshot?.findings.find((item) => Array.isArray(item.contributions));
  const contributions = records(finding?.attribution ?? finding?.contributions);
  const failureId = "verified-failure";
  const nodes: Node[] = contributions.map((item, index) => ({
    id: text(item.factor, `factor-${index}`),
    position: { x: 24 + (index % 3) * 215, y: 32 + Math.floor(index / 3) * 128 },
    data: {
      label: `${text(item.factor).replaceAll("_", " ")} · ${percent(item.contribution, 1)}`,
    },
    className: "causal-node",
  }));
  nodes.push({
    id: failureId,
    position: { x: 700, y: 108 },
    data: { label: text(finding?.source_failure, "verified failure").replaceAll("_", " ") },
    className: "causal-node danger-node",
  });
  const edges: Edge[] = contributions.map((item, index) => ({
    id: `edge-${index}`,
    source: text(item.factor, `factor-${index}`),
    target: failureId,
    animated: true,
    style: {
      stroke: "#ff6b35",
      strokeWidth: Math.max(1.2, numeric(item.contribution) * 10),
    },
  }));
  const sourceEvidence = record(finding?.source_evidence);
  const sourceTrace =
    traceHref(snapshot, sourceEvidence.source_trace_id) ??
    traceHref(snapshot, finding?.completion_trace_id);
  return (
    <section className="screen" data-testid="causal-graph">
      <div className="section-heading">
        <div>
          <span className="eyebrow">FORK · CONTROLLED INTERVENTIONS</span>
          <h2>Counterfactual causal graph</h2>
        </div>
        <div className="heading-actions">
          <ModeBadge value="counterfactual" />
          <EvidenceLink href={sourceTrace ?? snapshot?.links.traces} />
        </div>
      </div>
      {contributions.length ? (
        <div className="causal-layout">
          <article className="flow-wrap">
            <ReactFlow nodes={nodes} edges={edges} fitView minZoom={0.65}>
              <Background color="#203047" gap={22} />
              <Controls showInteractive={false} />
            </ReactFlow>
          </article>
          <aside className="panel attribution-panel">
            <div className="panel-title"><GitBranch size={15} /> Contribution with 95% CI</div>
            <div className="commitment">
              <span>Earliest commitment</span>
              <strong>{text(finding?.earliest_commitment_point).replaceAll("_", " ")}</strong>
            </div>
            {contributions.map((item) => (
              <div className="contribution-row" key={text(item.factor)}>
                <div><span>{text(item.factor).replaceAll("_", " ")}</span><strong>{percent(item.contribution)}</strong></div>
                <div className="ci-track">
                  <span
                    style={{
                      left: `${numeric(item.confidence_low) * 100}%`,
                      width: `${Math.max(1, (numeric(item.confidence_high) - numeric(item.confidence_low)) * 100)}%`,
                    }}
                  />
                  <i style={{ left: `${numeric(item.contribution) * 100}%` }} />
                </div>
                <small>{percent(item.confidence_low)} – {percent(item.confidence_high)}</small>
              </div>
            ))}
            <div className="causal-meta">
              <span>{numeric(finding?.shapley_samples)} attribution samples</span>
              <span>{numeric(finding?.completed_branch_count ?? finding?.branch_count)} branches</span>
            </div>
          </aside>
        </div>
      ) : (
        <Empty title="Causal evidence unavailable" icon={GitBranch} />
      )}
    </section>
  );
}

function AuthorityFrontier({ snapshot }: { snapshot: Snapshot | null }) {
  const frontier = snapshot?.frontier[0];
  const points = records(frontier?.points);
  const safeIndex = numeric(frontier?.maximum_safe_authority_index, -1);
  const chart = points.map((point) => ({
    level: numeric(point.level_index),
    completion: numeric(point.verified_completion) * 100,
    parity: numeric(point.evidence_parity) * 100,
    policy: numeric(point.policy_completeness) * 100,
    safe: Boolean(point.supported),
  }));
  return (
    <section className="screen" data-testid="authority-frontier">
      <div className="section-heading">
        <div>
          <span className="eyebrow">FRONTIER · SIX AUTHORITY LEVELS</span>
          <h2>Maximum evidence-supported autonomy</h2>
        </div>
        <div className="frontier-verdict">
          <span>Safe frontier</span>
          <strong>Level {safeIndex >= 0 ? safeIndex : "UNKNOWN"}</strong>
          <small>{text(frontier?.maximum_safe_authority_label)}</small>
        </div>
      </div>
      {points.length ? (
        <>
          <div className="frontier-layout">
            <article className="panel frontier-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chart} margin={{ top: 12, right: 18, left: -12, bottom: 4 }}>
                  <CartesianGrid stroke="#1b2940" vertical={false} />
                  <XAxis dataKey="level" stroke="#6c7c95" tickLine={false} />
                  <YAxis domain={[90, 100]} stroke="#6c7c95" tickLine={false} />
                  <Tooltip contentStyle={{ background: "#0a1320", border: "1px solid #273850" }} />
                  <Legend />
                  <ReferenceLine x={safeIndex} stroke="#ff6b35" strokeDasharray="4 4" label={{ value: "SAFE LIMIT", fill: "#ff8a5b", position: "insideTopRight" }} />
                  <Line dataKey="completion" name="Verified completion" stroke="#49d8e5" strokeWidth={3} dot={{ r: 4 }} />
                  <Line dataKey="parity" name="Evidence parity" stroke="#f1b84a" strokeWidth={2} dot={{ r: 3 }} />
                  <Line dataKey="policy" name="Policy completeness" stroke="#a892ff" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </article>
            <aside className="frontier-points">
              {points.map((point) => (
                <article
                  className={`frontier-point ${point.supported ? "supported" : "unsupported"}`}
                  key={String(point.level_index)}
                >
                  <div><span>LEVEL {numeric(point.level_index)}</span><StateBadge value={point.supported ? "SUPPORTED" : "BLOCKED"} /></div>
                  <strong>{text(point.authority_level).replaceAll("_", " ")}</strong>
                  <p>{percent(point.verified_completion)} complete · {numeric(point.unsafe_attempts)} unsafe attempts · {numeric(point.escaped_unsafe_effects)} escaped</p>
                  <EvidenceLink
                    href={evidenceHref(snapshot, Array.isArray(point.evidence_references) ? point.evidence_references : []) ?? traceHref(snapshot, point.trace_id)}
                    compact
                  />
                </article>
              ))}
            </aside>
          </div>
          <div className="frontier-footer">
            <ModeBadge value={frontier?.execution_mode} />
            <span>{numeric(frontier?.trial_count_per_level).toLocaleString()} trials per level</span>
            <EvidenceLink href={traceHref(snapshot, frontier?.trace_id)} />
          </div>
        </>
      ) : (
        <Empty title="Authority frontier unavailable" icon={Activity} />
      )}
    </section>
  );
}

function SafetyCase({ snapshot }: { snapshot: Snapshot | null }) {
  const certificates = snapshot?.summary?.certificates ?? [];
  const certificate =
    certificates.find((item) => item.candidate_id === "candidate-v2-fixed") ??
    certificates[0];
  const safetyCase = record(certificate?.safety_case);
  const nodes = records(safetyCase.nodes);
  const grouped = ["claim", "evidence", "assumption", "restriction", "residual_risk"].map(
    (kind) => [kind, nodes.filter((node) => node.kind === kind)] as const,
  );
  const verdicts = Array.from(new Set(certificates.map((item) => text(item.verdict))));
  return (
    <section className="screen" data-testid="safety-case">
      <div className="section-heading">
        <div>
          <span className="eyebrow">CLEARANCE · CLAIMS TO EVIDENCE</span>
          <h2>Structured safety argument</h2>
        </div>
        <div className="verdict-set" aria-label="Observed certificate verdicts">
          {verdicts.map((verdict) => <StateBadge value={verdict} key={verdict} />)}
        </div>
      </div>
      {nodes.length ? (
        <div className="safety-columns">
          {grouped.map(([kind, items]) => (
            <section className={`safety-column safety-${kind}`} key={kind}>
              <div className="safety-column-title">
                <span>{kind.replaceAll("_", " ")}</span>
                <strong>{items.length}</strong>
              </div>
              <div className="safety-column-content">
                {items.map((node) => (
                  <article className="safety-node" key={text(node.node_id)}>
                    <strong>{text(node.text)}</strong>
                    {node.evidence_url ? (
                      <EvidenceLink href={text(node.evidence_url)} compact />
                    ) : (
                      <span className="node-id">{text(node.node_id)}</span>
                    )}
                  </article>
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : (
        <Empty title="Safety case unavailable" icon={ShieldCheck} />
      )}
    </section>
  );
}

function CertificateScreen({ snapshot }: { snapshot: Snapshot | null }) {
  const certificates = snapshot?.summary?.certificates ?? [];
  const certificate =
    certificates.find((item) => item.candidate_id === "candidate-v2-fixed") ??
    certificates[0];
  const verifications = snapshot?.verifications ?? [];
  const verification = verifications.find(
    (item) => item.certificate_id === certificate?.certificate_id && item.reason === "valid",
  );
  const restrictions = Array.isArray(certificate?.restrictions)
    ? certificate.restrictions
    : [];
  const runtime = snapshot?.runtime;
  const suspension = runtime?.suspensions?.find(
    (item) => item.certificate_id === certificate?.certificate_id,
  ) ?? runtime?.suspensions?.[0];
  const rollback = runtime?.rollbacks?.find(
    (item) => item.certificate_id === suspension?.certificate_id,
  ) ?? runtime?.rollbacks?.[0];
  const rollout = record(runtime?.rollout);
  const delegation = record(snapshot?.delegation);
  const delegationDecision = record(delegation.decision);
  const delegationPayload = record(delegation.delegation);
  const delegator = record(delegationPayload.delegator);
  const delegate = record(delegationPayload.delegate);
  const gate = record(delegation.gate);
  const signatureValid = Boolean(verification?.valid);
  if (!certificate) {
    return <section className="screen"><Empty title="No flight certificate issued" icon={FileKey} /></section>;
  }
  return (
    <section className="screen certificate-screen" data-testid="certificate-screen">
      <div className="section-heading">
        <div>
          <span className="eyebrow">CLEARANCE · WATCHTOWER · CHAIN OF CUSTODY</span>
          <h2>Certificate and runtime authority</h2>
        </div>
        <EvidenceLink href={snapshot?.links.alerts} label="Alert history" />
      </div>
      <div className="certificate-layout">
        <article className="certificate-card">
          <div className="certificate-seal"><Orbit size={36} /><span>ORBITAL Σ</span></div>
          <div className="certificate-heading">
            <span className="eyebrow">SIGNED FLIGHT AUTHORITY</span>
            <h3 className={`verdict-${text(certificate.verdict).toLowerCase().replaceAll("-", "")}`}>
              {text(certificate.verdict)}
            </h3>
            <code>{text(certificate.certificate_id)}</code>
          </div>
          <div className="certificate-metrics">
            <Metric label="Candidate" value={text(certificate.candidate_id)} />
            <Metric label="Authority" value={text(certificate.granted_authority)} tone="orange" />
            <Metric label="Maximum refund" value={`$${numeric(certificate.maximum_refund_usd).toFixed(2)}`} />
            <Metric label="Canary ceiling" value={`${numeric(certificate.canary_percentage)}%`} />
          </div>
          <div className={`signature-status ${signatureValid ? "valid" : "unknown"}`}>
            {signatureValid ? <BadgeCheck size={18} /> : <KeyRound size={18} />}
            <div>
              <strong>{signatureValid ? "Ed25519 signature verified" : "Verification evidence unavailable"}</strong>
              <span>{text(verification?.reason, "UNKNOWN")} · {text(certificate.public_key_id)}</span>
            </div>
            <EvidenceLink href={traceHref(snapshot, verification?.trace_id)} compact />
          </div>
          <div className="restriction-list">
            <span>Authority restrictions</span>
            {restrictions.length ? restrictions.map((item) => (
              <div key={String(item)}><LockKeyhole size={13} /><span>{String(item)}</span></div>
            )) : <p>No restrictions recorded.</p>}
          </div>
          <div className="signature-code">
            <span>Signature</span>
            <code>{text(certificate.signature).slice(0, 88)}…</code>
          </div>
        </article>
        <div className="runtime-stack">
          <article className="panel runtime-card" data-testid="rollback-status">
            <div className="panel-title"><RotateCcw size={15} /> Runtime attestation</div>
            <div className="runtime-grid">
              <Metric label="Certificate" value={text(suspension?.status, "ACTIVE")} tone={suspension ? "red" : "cyan"} />
              <Metric label="Candidate traffic" value={`${numeric(rollback?.candidate_traffic_percentage ?? rollout.percentage)}%`} tone={suspension ? "red" : "cyan"} />
              <Metric label="Active candidate" value={text(rollback?.active_candidate ?? rollout.candidate_id)} tone="orange" />
              <Metric label="Rollback" value={rollback ? "RESTORED" : "NOT TRIGGERED"} tone={rollback ? "cyan" : "muted"} />
            </div>
            {rollback ? (
              <>
                <div className="alert-detail"><AlertTriangle size={14} /><span>{text(rollback.reason)}</span></div>
                <EvidenceLink
                  href={evidenceHref(snapshot, Array.isArray(rollback.evidence_links) ? rollback.evidence_links : []) ?? traceHref(snapshot, rollback.watchtower_trace_id)}
                />
              </>
            ) : (
              <Empty title="No suspension or rollback event" icon={ShieldCheck} />
            )}
          </article>
          <article className="panel delegation-card" data-testid="delegation-denial">
            <div className="panel-title"><Users size={15} /> Delegation custody</div>
            {Object.keys(delegationDecision).length ? (
              <>
                <div className="delegation-chain">
                  <div><Bot size={18} /><strong>{text(delegator.agent_id)}</strong><small>parent</small></div>
                  <div className="delegation-arrow"><Ban size={18} /><span>{strings(delegationPayload.delegated_tools).join(", ") || "delegated action"}</span></div>
                  <div><Bot size={18} /><strong>{text(delegate.agent_id)}</strong><small>child</small></div>
                </div>
                <div className="delegation-outcome">
                  <StateBadge value={delegationDecision.evidence_state} />
                  <strong>{strings(delegationDecision.detections).join(", ").replaceAll("_", " ") || "No detection"}</strong>
                </div>
                <div className="custody-facts">
                  <span>OPA {delegationDecision.opa_allowed === false ? "DENIED" : "UNKNOWN"}</span>
                  <span>GATE {numeric(gate.status_code) || "UNKNOWN"}</span>
                  <span>Effect {delegation.external_effect_occurred ? "OBSERVED" : "NONE"}</span>
                </div>
                <EvidenceLink href={traceHref(snapshot, delegation.trace_id)} />
              </>
            ) : (
              <Empty title="Delegation evidence unavailable" icon={Users} />
            )}
          </article>
        </div>
      </div>
    </section>
  );
}

function AppStatus({
  snapshot,
  loading,
  error,
  onRefresh,
}: {
  snapshot: Snapshot | null;
  loading: boolean;
  error: string | null;
  onRefresh: () => void;
}) {
  const sensors = record(snapshot?.sensors);
  const sensorComplete = sensors.complete === true;
  return (
    <div className="header-actions">
      {error && <span className="header-error"><ServerCrash size={13} />{error}</span>}
      <SourceHealth snapshot={snapshot} />
      <span className={`sensor-summary ${sensorComplete ? "online" : "degraded"}`}>
        {sensorComplete ? <Signal size={13} /> : <Unplug size={13} />}
        {sensorComplete ? "sensors online" : "sensor state unknown"}
      </span>
      <span className="header-time">
        {snapshot ? new Date(snapshot.generatedAt).toLocaleTimeString() : "—"}
      </span>
      <button aria-label="Refresh telemetry" onClick={onRefresh} className="icon-button">
        <RefreshCw className={loading ? "spinning-icon" : ""} size={16} />
      </button>
    </div>
  );
}

export default function Home() {
  const [screen, setScreen] = useState<Screen>("launch");
  const { snapshot, loading, error, refresh } = useSnapshot();
  const reduceMotion = useReducedMotion();
  const active = useMemo(
    () => navigation.find((item) => item.id === screen),
    [screen],
  );
  const campaign = snapshot?.summary?.campaigns?.[0] ?? null;
  const backgroundRefresh = useCallback(() => void refresh(true), [refresh]);
  const stream = useCampaignStream(campaign, backgroundRefresh);
  const screens: Record<Screen, React.ReactNode> = {
    launch: (
      <LaunchConsole
        snapshot={snapshot}
        campaign={campaign}
        stream={stream}
        onRefresh={backgroundRefresh}
      />
    ),
    evidence: <EvidenceParity snapshot={snapshot} />,
    replay: <ReplayTheater snapshot={snapshot} campaign={campaign} stream={stream} />,
    causal: <CausalGraph snapshot={snapshot} />,
    frontier: <AuthorityFrontier snapshot={snapshot} />,
    safety: <SafetyCase snapshot={snapshot} />,
    certificate: <CertificateScreen snapshot={snapshot} />,
  };
  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon"><Orbit /></div>
          <div><strong>ORBITAL <em>Σ</em></strong><span>MISSION CONTROL</span></div>
        </div>
        <nav aria-label="Mission Control screens">
          {navigation.map((item) => (
            <button
              key={item.id}
              onClick={() => setScreen(item.id)}
              className={screen === item.id ? "active" : ""}
              aria-current={screen === item.id ? "page" : undefined}
            >
              <item.icon size={17} />
              <span>{item.label}</span>
              {screen === item.id && <ChevronRight size={14} />}
            </button>
          ))}
        </nav>
        <div className="sidebar-footer">
          <div className={`connection ${snapshot?.connected ? "online" : "offline"}`}>
            <span />{snapshot?.connected ? "EVIDENCE PLANE CONNECTED" : "EVIDENCE PLANE DEGRADED"}
          </div>
          <small>FLIGHT ASSURANCE · PHASE 7</small>
        </div>
      </aside>
      <div className="main-column">
        <header>
          <div>
            <span className="breadcrumb">ORBITAL Σ / {active?.label.toUpperCase()}</span>
            <h1>{active?.label}</h1>
          </div>
          <AppStatus
            snapshot={snapshot}
            loading={loading}
            error={error}
            onRefresh={() => void refresh()}
          />
        </header>
        {loading && !snapshot ? (
          <div className="initial-loading" role="status">
            <Orbit size={34} />
            <strong>Establishing evidence channels</strong>
            <span>Loading live ORBITAL and SigNoz state…</span>
          </div>
        ) : (
          <motion.div
            key={screen}
            initial={reduceMotion ? false : { opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: reduceMotion ? 0 : 0.18 }}
          >
            {screens[screen]}
          </motion.div>
        )}
      </div>
    </main>
  );
}
