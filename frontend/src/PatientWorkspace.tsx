import './patient-workspace-polish.css';
import SourceCard from './SourceCard';
import RecordForm from './RecordForm';
import LabTrends from './LabTrends';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';

type Patient = {
  id: string;
  first_name: string;
  last_name: string;
  medical_record_number: string;
  date_of_birth: string;
};
type Encounter = {
  id: string;
  patient_id: string;
  visited_at: string;
  reason: string;
  notes: string | null;
};
type Lab = {
  id: string;
  test_name: string;
  value: string;
  unit: string;
  collected_at: string;
  reference_low: string | null;
  reference_high: string | null;
  reference_flag: string;
};
type Score = {
  model_version: string;
  scoring_version: string;
  anomaly_score: number;
  threshold: number;
  flagged_for_review: boolean;
  largest_error_feature?: string;
  interpretation?: string;
  known_limitations?: string[];
};
type Snapshot = {
  collected_at?: string;
  input_measurements?: Record<string, number>;
  source_lab_result_ids?: Record<string, string[]>;
  newer_unusable_panel_count?: number;
  result: Score;
};
type History = {
  history_id: string;
  scored_at: string;
  snapshot: Snapshot;
};
type Source = Record<string, unknown>;
type Answer = {
  answer?: string;
  summary?: string;
  answer_method?: string;
  answer_status?: string;
  summary_status?: string;
  insufficient_information?: boolean;
  scope?: string;
  notice?: string;
  source_refs?: string[];
  sources?: Record<string, Source>;
  retrieval_coverage?: unknown;
  source_data?: unknown;
  verified_record_facts?: { record_statements?: string[] };
};
type AgentReply = {
  result: Answer;
  trace?: { step: string; tool?: string; method?: string; status?: string }[];
};
type Auth = { token: string; onUnauthorized: () => void };

class RequestError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function api<T>(path: string, token: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`/api${path}`, { ...options, headers });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data?.detail;
    let message = `Request failed (${response.status}).`;
    if (typeof detail === 'string') message = detail;
    else if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
      message = [detail.message, detail.reason].filter(Boolean).join(' ') || message;
    } else if (Array.isArray(detail)) {
      message = detail.map((item: { msg?: string }) => item.msg || 'Invalid input').join('; ');
    }
    throw new RequestError(response.status, message);
  }
  return data as T;
}

function errorText(error: unknown, onUnauthorized: () => void) {
  if (error instanceof RequestError && error.status === 401) onUnauthorized();
  return error instanceof Error ? error.message : 'The request could not be completed.';
}

function dateTime(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
  });
}

const names: Record<string, string> = {
  '2339-0': 'Glucose', '38483-4': 'Creatinine',
  '6299-2': 'Urea nitrogen', '2947-0': 'Sodium',
  '6298-4': 'Potassium', '2069-3': 'Chloride',
  '49765-1': 'Calcium', '20565-8': 'Total CO₂',
};
function label(value: string) {
  return names[value] || value.replaceAll('_', ' ');
}

function Pager({ offset, count, busy, onPage }: {
  offset: number; count: number; busy: boolean; onPage: (offset: number) => void;
}) {
  return <div className="pw-pager">
    <span>Page {offset / 20 + 1}</span>
    <div>
      <button className="button secondary" disabled={busy || offset === 0}
        onClick={() => onPage(offset - 20)}>← Previous</button>
      <button className="button secondary" disabled={busy || count <= 20}
        onClick={() => onPage(offset + 20)}>Next →</button>
    </div>
  </div>;
}

function ScoreCard({ entry }: { entry: History }) {
  const score = entry.snapshot.result;
  return <article className="pw-score">
    <div className="pw-row">
      <span className={`pw-badge ${score.flagged_for_review ? 'pw-amber' : ''}`}>
        {score.flagged_for_review ? 'Flagged for review' : 'Not flagged by model'}
      </span>
      <span className="pw-small">{dateTime(entry.scored_at)}</span>
    </div>
    <div className="pw-score-numbers">
      <div><small>Anomaly score</small><strong>{score.anomaly_score.toFixed(4)}</strong></div>
      <div><small>Model threshold</small><strong>{score.threshold.toFixed(4)}</strong></div>
    </div>
    <p className="pw-small">Panel collected: {entry.snapshot.collected_at
      ? dateTime(entry.snapshot.collected_at) : 'Not provided'}</p>
    {(entry.snapshot.newer_unusable_panel_count || 0) > 0 && <p className="error-box">
      {entry.snapshot.newer_unusable_panel_count} newer unusable panel(s) were skipped.
    </p>}
    <p className="pw-small">{score.interpretation || 'Statistical unusualness, not a diagnosis. An unflagged panel does not establish clinical normality.'}</p>
    <details className="pw-details">
      <summary>Model information & saved inputs</summary>
      <p>Model: {score.model_version}<br />Scoring: {score.scoring_version}</p>
      <p>Scoring record: <span className="patient-id">{entry.history_id}</span></p>
      {score.largest_error_feature && <p>Largest reconstruction discrepancy: {label(score.largest_error_feature)}. This does not prove which measurement is incorrect.</p>}
      {score.known_limitations?.map(item => <p key={item}>• {item}</p>)}
      <pre>{JSON.stringify(entry.snapshot, null, 2)}</pre>
    </details>
  </article>;
}

function EncounterContent({ encounter, token, onUnauthorized, role }: Auth & { encounter: Encounter; role: string }) {
  const [tab, setTab] = useState<'labs' | 'scores'>('labs');
  return <section className="pw-encounter">
    <header className="pw-encounter-heading">
      <p className="eyebrow">ENCOUNTER RECORD</p>
      <h2>{encounter.reason}</h2>
      <p className="pw-small">{dateTime(encounter.visited_at)}</p>
      <details className="pw-details">
        <summary>Visit notes</summary>
        <p className="pw-prose">{encounter.notes || 'No notes recorded.'}</p>
      </details>
      <details className="pw-details">
        <summary>Technical details</summary>
        <p className="patient-id">Visit ID: {encounter.id}</p>
      </details>
    </header>
    <div className="pw-tabs" aria-label="Encounter views">
      <button aria-pressed={tab === 'labs'} onClick={() => setTab('labs')}>Lab measurements</button>
      <button aria-pressed={tab === 'scores'} onClick={() => setTab('scores')}>Anomaly scores</button>
    </div>
    {tab === 'labs'
      ? <Labs role={role} key={encounter.id} encounterId={encounter.id} token={token} onUnauthorized={onUnauthorized} />
      : <Scores key={encounter.id} encounterId={encounter.id} token={token} onUnauthorized={onUnauthorized} />}
  </section>;
}

function Labs({ encounterId, token, onUnauthorized, role }: Auth & { encounterId: string; role: string }) {
  const [rows, setRows] = useState<Lab[]>([]);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const unauthorized = useRef(onUnauthorized);
  unauthorized.current = onUnauthorized;

  useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setError(''); setRows([]);
    api<Lab[]>(`/encounters/${encounterId}/labs?limit=21&offset=${offset}`,
      token, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setRows(data); })
      .catch(err => { if (!controller.signal.aborted) setError(errorText(err, unauthorized.current)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [encounterId, token, offset, refresh]);

  return <div className="pw-section">
    {['admin','doctor'].includes(role) && <>
      <RecordForm
        title="Add complete chemistry panel"
        path={`/encounters/${encounterId}/chemistry-panel`}
        token={token}
        onUnauthorized={onUnauthorized}
        onSaved={() => {setOffset(0); setRefresh(v => v + 1);}}
        description="All eight measurements are saved together. Enter values in the displayed units. Collection time uses your computer's local timezone. Saving does not automatically run the anomaly model."
        fields={[
          {name:'collected_at',label:'Collection date and time',type:'datetime-local'},
          ...[
            ['glucose','Glucose · mg/dL'],
            ['creatinine','Creatinine · mg/dL'],
            ['urea_nitrogen','Urea nitrogen · mg/dL'],
            ['sodium','Sodium · mmol/L'],
            ['potassium','Potassium · mmol/L'],
            ['chloride','Chloride · mmol/L'],
            ['calcium','Calcium · mg/dL'],
            ['total_co2','Total CO₂ · mmol/L'],
          ].map(([name,label]) => ({name,label,type:'number'})),
        ]}
        transform={values => ({
          ...values,
          collected_at:new Date(values.collected_at).toISOString(),
        })}
      />
      <RecordForm
        title="Add individual lab result"
        path={`/encounters/${encounterId}/labs`}
        token={token}
        onUnauthorized={onUnauthorized}
        onSaved={() => {setOffset(0); setRefresh(v => v + 1);}}
        fields={[
          {name:'test_name',label:'Test name or code',max:200},
          {name:'value',label:'Recorded value',type:'number'},
          {name:'unit',label:'Unit',max:50},
          {name:'collected_at',label:'Collection date and time (local)',type:'datetime-local'},
          {name:'reference_low',label:'Reference low',type:'number',optional:true},
          {name:'reference_high',label:'Reference high',type:'number',optional:true},
        ]}
        transform={values => ({
          ...values,
          collected_at:new Date(values.collected_at).toISOString(),
          reference_low:values.reference_low || null,
          reference_high:values.reference_high || null,
        })}
      />
    </>}
    <p className="pw-small">Stored values and units. Reference flags are separate from ML anomaly scores.</p>
    {busy ? <p role="status" className="state-box">Loading measurements…</p>
      : error ? <div role="alert" className="error-box">{error}<button className="button secondary" onClick={() => setRefresh(v => v + 1)}>Retry</button></div>
      : rows.length === 0 ? <div className="state-box">No lab measurements on this page.</div>
      : <div className="table-scroll"><table>
        <thead><tr><th>Measurement</th><th>Recorded value</th><th>Collected</th><th>Reference flag</th></tr></thead>
        <tbody>{rows.slice(0, 20).map(lab => <tr key={lab.id}>
          <td><strong>{label(lab.test_name)}</strong><small className="pw-code">{lab.test_name}</small></td>
          <td><strong>{lab.value}</strong> {lab.unit}</td>
          <td>{dateTime(lab.collected_at)}</td>
          <td>{label(lab.reference_flag)}</td>
        </tr>)}</tbody>
      </table></div>}
    <Pager offset={offset} count={rows.length} busy={busy} onPage={setOffset} />
  </div>;
}

function Scores({ encounterId, token, onUnauthorized }: Auth & { encounterId: string }) {
  const [rows, setRows] = useState<History[]>([]);
  const [offset, setOffset] = useState(0);
  const [busy, setBusy] = useState(true);
  const [scoring, setScoring] = useState(false);
  const [error, setError] = useState('');
  const [scoreError, setScoreError] = useState('');
  const [saved, setSaved] = useState('');
  const [refresh, setRefresh] = useState(0);
  const mutation = useRef<AbortController | null>(null);
  const unauthorized = useRef(onUnauthorized);
  unauthorized.current = onUnauthorized;

  useEffect(() => () => { mutation.current?.abort(); }, []);

  useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setError(''); setRows([]);
    api<History[]>(`/ml/encounters/${encounterId}/anomaly-history?limit=21&offset=${offset}`,
      token, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setRows(data); })
      .catch(err => { if (!controller.signal.aborted) setError(errorText(err, unauthorized.current)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [encounterId, token, offset, refresh]);

  async function score() {
    if (mutation.current) return;
    const controller = new AbortController();
    mutation.current = controller;
    setScoring(true); setScoreError(''); setSaved('');
    try {
      await api(`/ml/encounters/${encounterId}/anomaly-score`, token, {
        method: 'POST', signal: controller.signal,
      });
      if (!controller.signal.aborted) {
        setSaved('A new scoring-history record was saved.');
        setOffset(0); setRefresh(v => v + 1);
      }
    } catch (err) {
      if (!controller.signal.aborted) setScoreError(
        errorText(err, unauthorized.current) +
        ' If the connection was interrupted, refresh history before trying again.'
      );
    } finally {
      mutation.current = null;
      if (!controller.signal.aborted) setScoring(false);
    }
  }

  return <div className="pw-section">
    <div className="pw-score-action">
      <div><h3>Saved panel analysis</h3><p className="pw-small">Scores the latest complete, valid panel in this encounter and saves a new history entry.</p></div>
      <button className="button primary" disabled={scoring || busy} onClick={() => void score()}>
        {scoring ? 'Scoring…' : 'Score & save panel'}
      </button>
    </div>
    <p className="pw-notice">Synthetic-data model. Scores are not disease probabilities. Repeated scoring creates separate history entries.</p>
    {saved && <p role="status" className="pw-notice">{saved}</p>}
    {scoreError && <p role="alert" className="error-box">{scoreError}</p>}
    <button className="button secondary" disabled={busy || scoring} onClick={() => setRefresh(v => v + 1)}>↻ Refresh history</button>
    {busy ? <p role="status" className="state-box">Loading scoring history…</p>
      : error ? <p role="alert" className="error-box">{error}</p>
      : rows.length === 0 ? <div className="state-box">No scoring history on this page.</div>
      : rows.slice(0, 20).map(entry => <ScoreCard key={entry.history_id} entry={entry} />)}
    <Pager offset={offset} count={rows.length} busy={busy || scoring} onPage={setOffset} />
  </div>;
}

function Assistant({ patient, token, onUnauthorized }: Auth & { patient: Patient }) {
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [asked, setAsked] = useState('');
  const [trace, setTrace] = useState<AgentReply['trace']>([]);
  const running = useRef<AbortController | null>(null);

  useEffect(() => () => running.current?.abort(), []);

  async function run(summary = false) {
    if (running.current) return;
    const text = question.trim();
    if (!summary && text.length < 3) return;
    const controller = new AbortController();
    running.current = controller;
    const timeout = window.setTimeout(() => controller.abort(), 240000);
    setBusy(true); setError(''); setAnswer(null); setTrace([]);
    setAsked(summary ? 'Summarize the latest encounter' : text);
    try {
      if (summary) {
        const result = await api<Answer>(`/ai/patients/${patient.id}/summary`, token, {
          method: 'POST', signal: controller.signal,
        });
        if (!controller.signal.aborted) setAnswer(result);
      } else {
        const result = await api<AgentReply>(`/ai/patients/${patient.id}/agent`, token, {
          method: 'POST', signal: controller.signal,
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ question: text }),
        });
        if (!controller.signal.aborted) { setAnswer(result.result); setTrace(result.trace); }
      }
    } catch (err) {
      setError(controller.signal.aborted
        ? 'The request was stopped or exceeded four minutes. Local generation may still be finishing.'
        : errorText(err, onUnauthorized));
    } finally {
      window.clearTimeout(timeout);
      running.current = null;
      setBusy(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run();
  }

  return <section className="pw-assistant">
    <div className="pw-assistant-heading">
      <span className="welcome-icon" aria-hidden="true">✧</span>
      <div><p className="eyebrow">PATIENT-SPECIFIC ASSISTANT</p><h2>Ask with context.</h2></div>
    </div>
    <p className="muted">Explore saved information for {patient.first_name} {patient.last_name}. Each question is independent.</p>
    <div className="pw-suggestions">
      {['What is the latest glucose value?', 'What prevented the patient from attending?', 'Has the latest score been reviewed?'].map(text =>
        <button key={text} disabled={busy} onClick={() => setQuestion(text)}>{text} ↗</button>)}
    </div>
    <form onSubmit={submit}>
      <label htmlFor="patient-question">Your question</label>
      <textarea id="patient-question" required minLength={3} maxLength={1000}
        placeholder="Ask about measurements, notes or recorded reviews…"
        value={question} disabled={busy} onChange={e => setQuestion(e.target.value)} />
      <div className="pw-row">
        <span className="pw-small">{question.length}/1000 characters</span>
        <button className="button primary" disabled={busy || question.trim().length < 3}>
          {busy ? 'Working…' : 'Ask assistant ↗'}
        </button>
      </div>
    </form>
    <button className="button secondary pw-summary-button" disabled={busy} onClick={() => void run(true)}>
      Summarize latest encounter
    </button>
    <p className="pw-small">AI questions use the patient context selected by the backend. Summaries cover the latest encounter, regardless of the encounter selected in the timeline.</p>
    {busy && <div className="pw-generation-state">
      <p role="status"><span className="spinner" />
        Reading saved context and preparing a response…
      </p>
      <button type="button" className="button secondary"
        onClick={() => running.current?.abort()}>
        Stop waiting
      </button>
      <small>Stops this browser request. Local model generation may continue.</small>
    </div>}
    {error && <p role="alert" className="error-box">{error}</p>}
    {answer && <article className="pw-answer">
      <p className="eyebrow">RESPONSE</p>
      <h3>{asked}</h3>
      <div className="pw-row">
        <span className="pw-badge">{label(answer.answer_status || answer.summary_status || 'generated_unverified')}</span>
        {answer.insufficient_information === true && <span className="pw-badge pw-amber">Insufficient information</span>}
      </div>
      <p className="pw-prose">{answer.answer || answer.summary || 'No answer text returned.'}</p>
      {answer.verified_record_facts?.record_statements?.map(item =>
        <p className="pw-notice" key={item}>{item}</p>)}
      {answer.notice && <p className="pw-small">{answer.notice}</p>}
      {answer.sources && Object.keys(answer.sources).length > 0 && <div>
        <h4>Supporting records</h4>
        {Object.entries(answer.sources).map(([ref, value]) =>
          <SourceCard key={ref} reference={ref} value={value} />
        )}
      </div>}
      <details className="pw-details"><summary>Retrieval scope & execution details</summary>
        <pre>{JSON.stringify({
          method: answer.answer_method,
          scope: answer.scope,
          coverage: answer.retrieval_coverage,
          trace,
          source_data: answer.source_data,
        }, null, 2)}</pre>
      </details>
    </article>}
  </section>;
}

export default function PatientWorkspace({ patient, token, onClose, onUnauthorized, role }:
  Auth & { patient: Patient; onClose: () => void; role: string }) {
  const [tab, setTab] = useState<'records' | 'assistant' | 'trends'>('records');
  const [encounters, setEncounters] = useState<Encounter[]>([]);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<Encounter | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  const unauthorized = useRef(onUnauthorized);
  unauthorized.current = onUnauthorized;

  useEffect(() => {
    heading.current?.focus({ preventScroll: true });
    heading.current?.scrollIntoView({ block: 'start' });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setError(''); setEncounters([]); setSelected(null);
    api<Encounter[]>(`/patients/${patient.id}/encounters?limit=21&offset=${offset}`,
      token, { signal: controller.signal })
      .then(data => {
        if (!controller.signal.aborted) {
          setEncounters(data); setSelected(data[0] || null);
        }
      })
      .catch(err => { if (!controller.signal.aborted) setError(errorText(err, unauthorized.current)); })
      .finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [patient.id, token, offset, refresh]);

  // Patient workspace polish v1
  const visibleEncounters = encounters.slice(0, 20);
  const selectedIndex = visibleEncounters.findIndex(
    encounter => encounter.id === selected?.id,
  );

  return <section className="pw-shell pw-polished" aria-label="Patient workspace">
    <header className="pw-header">
      <div><p className="eyebrow">PATIENT WORKSPACE</p>
        <h2 ref={heading} tabIndex={-1}>{patient.first_name} {patient.last_name}</h2>
        <div className="pw-identity-tags">
          <span>Medical record number <strong>{patient.medical_record_number}</strong></span>
          <span>Date of birth <strong>{patient.date_of_birth}</strong></span>
        </div>
        <details className="pw-patient-id">
          <summary>Technical details</summary>
          <code>{patient.id}</code>
        </details>
      </div>
      <button className="button secondary" onClick={onClose}>Close workspace ×</button>
    </header>
    <div className="pw-context-strip">
      <div>
        <small>WORKSPACE SCOPE</small>
        <strong>One patient. Connected records.</strong>
        <p>Choose an encounter for its labs and saved scores,
          or explore patient-level questions and trends.</p>
      </div>
      <div>
        <small>ENCOUNTERS ON THIS PAGE</small>
        <strong>{busy ? 'Loading…' : error ? 'Unavailable' : visibleEncounters.length}</strong>
        <p>Page {offset / 20 + 1}{encounters.length > 20 ? ' · More encounters available' : ''}</p>
      </div>
      <div>
        <small>YOUR ACCESS</small>
        <strong>{role.charAt(0).toUpperCase() + role.slice(1)}</strong>
        <p>{['admin', 'doctor'].includes(role)
          ? 'Patient and encounter entry available.'
          : 'Clinical records available for viewing.'}</p>
      </div>
    </div>
    <div className="pw-tabs pw-main-tabs" aria-label="Patient workspace sections">
      <button aria-pressed={tab === 'records'} onClick={() => setTab('records')}>01 / Clinical records</button>
      <button aria-pressed={tab === 'assistant'} onClick={() => setTab('assistant')}>02 / AI assistant</button>
      <button aria-pressed={tab === 'trends'} onClick={() => setTab('trends')}>03 / Lab trends</button>
    </div>
    {tab === 'assistant' ? <Assistant key={patient.id} patient={patient} token={token} onUnauthorized={onUnauthorized} />
      : tab === 'trends'
      ? <LabTrends patientId={patient.id} token={token} onUnauthorized={onUnauthorized} />
      : <div className="pw-record-layout">
        <aside className="pw-timeline">
          <div className="pw-row"><h3>Encounters</h3><button className="button secondary" disabled={busy} onClick={() => setRefresh(v => v + 1)} aria-label="Refresh encounters">↻</button></div>
          {['admin','doctor'].includes(role) && <RecordForm
            title="Add encounter"
            path={`/patients/${patient.id}/encounters`}
            token={token}
            onUnauthorized={onUnauthorized}
            onSaved={() => {setOffset(0); setRefresh(v => v + 1);}}
            fields={[
              {name:'visited_at',label:'Visit date and time (local)',type:'datetime-local'},
              {name:'reason',label:'Visit reason',max:500},
              {name:'notes',label:'Encounter notes',type:'textarea',max:10000,optional:true},
            ]}
            transform={values => ({
              ...values,
              visited_at:new Date(values.visited_at).toISOString(),
              notes:values.notes || null,
            })}
          />}
          {busy ? <p role="status" className="pw-small">Loading encounters…</p>
            : error ? <p role="alert" className="error-box">{error}</p>
            : encounters.length === 0 ? <p className="pw-small">No encounters on this page.</p>
            : encounters.slice(0, 20).map(encounter => <button
              className={`pw-visit ${selected?.id === encounter.id ? 'pw-selected' : ''}`}
              key={encounter.id} onClick={() => setSelected(encounter)}
              aria-pressed={selected?.id === encounter.id}>
              <small>{dateTime(encounter.visited_at)}</small>
              <strong>{encounter.reason}</strong><span>View encounter ↗</span>
            </button>)}
          <Pager offset={offset} count={encounters.length} busy={busy} onPage={setOffset} />
        </aside>
        <div className="pw-record-content">
          {selected && <section className="pw-selection-summary">
            <div className="pw-selection-title">
              <div>
                <p className="eyebrow">SELECTED ENCOUNTER</p>
                <h3>{selected.reason}</h3>
                <p>{dateTime(selected.visited_at)}</p>
              </div>
              <span className="pw-selection-position">
                {selectedIndex >= 0 ? selectedIndex + 1 : '—'} / {visibleEncounters.length}
                <small>on this page</small>
              </span>
            </div>
            <div className="pw-selection-actions">
              <button className="button secondary"
                disabled={busy || selectedIndex <= 0}
                onClick={() => {
                  if (selectedIndex > 0) {
                    setSelected(visibleEncounters[selectedIndex - 1]);
                  }
                }}>← Previous encounter</button>
              <button className="button secondary"
                disabled={busy || selectedIndex < 0 ||
                  selectedIndex >= visibleEncounters.length - 1}
                onClick={() => {
                  if (selectedIndex >= 0 &&
                      selectedIndex < visibleEncounters.length - 1) {
                    setSelected(visibleEncounters[selectedIndex + 1]);
                  }
                }}>Next encounter →</button>
            </div>
            <p className="pw-selection-hint">
              Labs and scores below belong to this encounter.
              AI summaries use the latest encounter; questions and trends
              have their own displayed retrieval scope.
            </p>
          </section>}
          {selected ? <EncounterContent role={role} key={selected.id} encounter={selected} token={token} onUnauthorized={onUnauthorized} />
            : <div className="state-box">Select an encounter to explore its saved records.</div>}
        </div>
      </div>}
  </section>;
}
