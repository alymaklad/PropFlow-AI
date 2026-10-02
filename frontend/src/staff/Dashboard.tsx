import { useCallback, useEffect, useState } from "react";
import { AuthError, type DeadLetter, type Handoff, type Overview, type RecentLead, staffFetch } from "../api";
import { percent, plural, when } from "../format";

type Props = { onSignOut: () => void; onAuthLost: () => void };
type Period = "day" | "week";

const SOURCE: Record<string, string> = { form: "Web form", email: "Email", manual: "Manual", whatsapp: "WhatsApp" };

// Short labels for handoff reasons in the figures (the queue shows the full sentence).
const REASON: Record<string, string> = {
  ai_unavailable: "AI unavailable",
  ai_output_invalid: "AI output invalid",
  low_confidence: "low AI confidence",
  no_matching_property: "no matching home",
  injection_suspected: "suspected injection",
  customer_requested_human: "asked for a person",
  conflicting_requirements: "conflicting requirements",
  unsupported_language: "not in English",
  out_of_scope_rental: "rental request",
};

const capitalise = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

function duration(minutes: number | null): string {
  if (minutes === null) return "";
  if (minutes < 1) return `${Math.max(1, Math.round(minutes * 60))} seconds`;
  if (minutes < 90) return `${Math.round(minutes)} minutes`;
  return `${(minutes / 60).toFixed(1)} hours`;
}

function list(counts: Record<string, number>, names: Record<string, string> = {}): string {
  const entries = Object.entries(counts).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return "none";
  return entries.map(([k, v]) => `${v} ${names[k] ?? k.replace(/_/g, " ")}`).join(", ");
}

function outcome(lead: RecentLead): string {
  if (lead.kind === "reply") return "Customer replied";
  if (lead.status === "rejected") return "Rejected as incomplete";
  if (lead.status === "failed") return "Failed, see failed runs";
  if (lead.status !== "completed") return "In progress";
  if (lead.handed_off) return "Handed to a salesperson";
  if (lead.crm_action === "matched_contact") return "Added to an existing lead";
  if (lead.crm_action === "created" || lead.crm_action === "updated") return "New lead, automated reply";
  return lead.odoo_lead_id ? "Processed" : "Opted out, no lead";
}

export function Dashboard({ onSignOut, onAuthLost }: Props) {
  const [period, setPeriod] = useState<Period>("day");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [handoffs, setHandoffs] = useState<Handoff[] | null>(null);
  const [deadLetters, setDeadLetters] = useState<DeadLetter[] | null>(null);
  const [leads, setLeads] = useState<RecentLead[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [updated, setUpdated] = useState<Date | null>(null);

  const load = useCallback(async () => {
    try {
      const [o, h, d, l] = await Promise.all([
        staffFetch<Overview>(`/overview?period=${period}`),
        staffFetch<Handoff[]>("/handoffs"),
        staffFetch<DeadLetter[]>("/dead-letters"),
        staffFetch<RecentLead[]>("/leads?limit=20"),
      ]);
      setOverview(o); setHandoffs(h); setDeadLetters(d); setLeads(l);
      setError(null); setUpdated(new Date());
    } catch (e) {
      if (e instanceof AuthError) onAuthLost();
      else setError(e instanceof Error ? e.message : "The dashboard couldn't load.");
    }
  }, [period, onAuthLost]);

  useEffect(() => {
    load();
    const timer = setInterval(load, 60_000);
    return () => clearInterval(timer);
  }, [load]);

  const overdue = handoffs?.filter((h) => h.overdue).length ?? 0;

  return (
    <div className="staff">
      <header className="staff-header">
        <p className="staff-brand">PropFlow staff</p>
        <div className="period" role="group" aria-label="Report period">
          <button type="button" aria-pressed={period === "day"} onClick={() => setPeriod("day")}>Last 24 hours</button>
          <button type="button" aria-pressed={period === "week"} onClick={() => setPeriod("week")}>Last 7 days</button>
        </div>
        <div className="staff-header-end">
          {updated && <span className="updated">Updated {updated.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}</span>}
          <button type="button" className="btn btn-quiet" onClick={load}>Refresh</button>
          <button type="button" className="btn btn-quiet" onClick={onSignOut}>Sign out</button>
        </div>
      </header>

      {error && <p className="staff-error" role="alert">{error} Data below may be out of date.</p>}

      <main className="staff-grid">
        <section className="panel panel-handoffs" aria-labelledby="h-handoffs">
          <h1 id="h-handoffs">
            {handoffs === null ? "Handoffs" : handoffs.length === 0 ? "No customers are waiting for a salesperson"
              : `${plural(handoffs.length, "customer")} waiting for a salesperson`}
          </h1>
          {overdue > 0 && <p className="lede-alert">{overdue} past the contact deadline.</p>}
          <ul className="handoffs">
            {handoffs?.map((h) => (
              <li key={h.id} className={h.overdue ? "handoff is-overdue" : "handoff"}>
                <div className="handoff-main">
                  <p className="handoff-who">
                    {h.customer ?? "Unnamed customer"}
                    {h.lead_id && <span className="handoff-lead num">Lead {h.lead_id}</span>}
                  </p>
                  <p className="handoff-why">{capitalise(h.reasons.join("; "))}.</p>
                  <p className="handoff-owner">
                    {h.owner ?? "No owner"}{h.priority && `, ${h.priority} priority`}
                    {h.reminded && ", reminder sent"}{h.escalated && ", manager told"}
                  </p>
                </div>
                <div className="handoff-side">
                  <p className="handoff-due">{h.overdue ? `Overdue since ${h.due_text}` : `Contact by ${h.due_text}`}</p>
                  {h.lead_url && <a href={h.lead_url} target="_blank" rel="noreferrer">Open in Odoo</a>}
                </div>
              </li>
            ))}
          </ul>
        </section>

        <section className="panel panel-figures" aria-labelledby="h-figures">
          <h2 id="h-figures">{period === "day" ? "In the last 24 hours" : "In the last 7 days"}</h2>
          {overview ? <Figures o={overview} /> : <p className="muted">Loading figures...</p>}
        </section>

        <section className="panel panel-failures" aria-labelledby="h-failures">
          <h2 id="h-failures">
            {deadLetters === null ? "Failed runs" : deadLetters.length === 0 ? "No failed runs to deal with"
              : `${plural(deadLetters.length, "failed run")} to deal with`}
          </h2>
          <ul className="failures">
            {deadLetters?.map((d) => <FailedRun key={d.id} run={d} onDone={load} />)}
          </ul>
        </section>

        <section className="panel panel-leads" aria-labelledby="h-leads">
          <h2 id="h-leads">Latest inquiries</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th scope="col">Received</th><th scope="col">Customer</th><th scope="col">Channel</th>
                  <th scope="col">What happened</th><th scope="col">Score</th><th scope="col"><span className="visually-hidden">Link</span></th></tr>
              </thead>
              <tbody>
                {leads?.map((l, i) => (
                  <tr key={`${l.received_at}-${i}`}>
                    <td className="num">{when(l.received_at)}</td>
                    <td>{l.name ?? "Not given"}</td>
                    <td>{l.kind === "reply" ? "Email reply" : SOURCE[l.source] ?? l.source}</td>
                    <td className={l.status === "failed" ? "is-bad" : undefined}>{outcome(l)}</td>
                    <td className="num">{l.score ?? ""}{l.priority === "high" && <span className="tag-high">high</span>}</td>
                    <td>{l.lead_url && <a href={l.lead_url} target="_blank" rel="noreferrer">Odoo</a>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </main>
    </div>
  );
}

function Figures({ o }: { o: Overview }) {
  const valid = o.intake.received - o.intake.rejected_invalid;
  const done = o.intake.outcomes.completed ?? 0;
  const q = o.qualification.qualified_rate;
  const m = o.matching.matched_rate;
  const fr = o.first_response_minutes;
  const sync = o.crm_sync.success_rate;
  return (
    <ul className="figures">
      <li><strong className="num">{o.intake.received}</strong> inquiries arrived: {list(o.intake.received_by_source, SOURCE)}.</li>
      <li><strong className="num">{done} of {valid}</strong> valid inquiries were fully processed ({percent(done, valid)}).
        {o.intake.rejected_invalid > 0 && ` ${o.intake.rejected_invalid} were rejected as incomplete.`}</li>
      <li><strong className="num">{q.numerator} of {q.denominator}</strong> scored leads are high or standard priority.</li>
      <li><strong className="num">{m.numerator} of {m.denominator}</strong> searches found matching homes.</li>
      <li>{fr.count ? <>First reply to the customer took a median of <strong className="num">{duration(fr.median)}</strong> over {plural(fr.count, "lead")}.</>
        : "No first replies were sent in this period."}</li>
      <li><strong className="num">{o.handoffs.created}</strong> handoffs to salespeople{o.handoffs.created > 0 && `: ${list(o.handoffs.by_reason, REASON)}`}.</li>
      <li><strong className="num">{o.followups.customer_replies}</strong> customer replies and <strong className="num">{o.followups.reminders_sent}</strong> reminders sent.</li>
      <li>Odoo updates succeeded <strong className="num">{sync.numerator} of {sync.denominator}</strong> times ({percent(sync.numerator, sync.denominator)}).</li>
      {Object.keys(o.workload).length > 0 && (
        <li>
          Leads per salesperson (new in period, open now):
          <ul className="workload">
            {Object.entries(o.workload).map(([name, w]) => (
              <li key={name}>{name}: <span className="num">{w.assigned_in_window} new, {w.open_leads} open</span></li>
            ))}
          </ul>
        </li>
      )}
      {o.odoo !== "ok" && <li className="is-bad">Odoo figures are missing: {o.odoo}.</li>}
    </ul>
  );
}

function FailedRun({ run, onDone }: { run: DeadLetter; onDone: () => void }) {
  const [busy, setBusy] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<string | null>(null);

  async function act(path: string, body?: object) {
    setBusy(true);
    try {
      const out = await staffFetch<{ resolution: string; status: string }>(path, { method: "POST", body: JSON.stringify(body ?? {}) });
      setResult(out.status === "replayed" ? `Replayed: ${out.resolution}.` : "Discarded.");
      setTimeout(onDone, 1200);
    } catch (e) {
      setResult(e instanceof Error ? e.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="failure">
      <p className="failure-what">{run.workflow}{run.last_node && `, at "${run.last_node}"`}</p>
      <p className="failure-error">{run.error}</p>
      <p className="failure-meta num">{when(run.created_at)}, {plural(run.attempts, "attempt")}</p>
      {result ? <p className="failure-result" role="status">{result}</p> : discarding ? (
        <form className="discard" onSubmit={(e) => { e.preventDefault(); act(`/dead-letters/${run.id}/discard`, { reason }); }}>
          <label htmlFor={`r-${run.id}`}>Why discard it?</label>
          <input id={`r-${run.id}`} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Fixed by hand in Odoo" />
          <div className="failure-actions">
            <button className="btn btn-danger" type="submit" disabled={busy || reason.trim().length < 3}>Discard</button>
            <button className="btn btn-quiet" type="button" onClick={() => setDiscarding(false)}>Keep it</button>
          </div>
        </form>
      ) : (
        <div className="failure-actions">
          {run.replayable && <button className="btn" type="button" disabled={busy} onClick={() => act(`/dead-letters/${run.id}/replay`)}>{busy ? "Replaying..." : "Replay"}</button>}
          <button className="btn btn-quiet" type="button" onClick={() => setDiscarding(true)}>Discard...</button>
        </div>
      )}
    </li>
  );
}
