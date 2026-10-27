import SavedPanel from './SavedPanel';
import './review-queue-enhancements.css';
import { useEffect, useRef, useState } from 'react';
import type { FormEvent } from 'react';

type ReviewStatus = 'needs_investigation' | 'confirmed_data_error' | 'reviewed_no_correction_needed';
type Review = {
  id: string;
  score_history_id?: string;
  status: ReviewStatus;
  reviewer_name: string;
  reviewer_user_id: string | null;
  note: string;
  created_at: string;
};
type Item = {
  patient_name?: string;
  medical_record_number?: string;
  patient_lookup_failed?: boolean;
  history_id: string;
  patient_id: string;
  encounter_id: string;
  collected_at: string;
  scored_at: string;
  model_version: string;
  scoring_version: string;
  anomaly_score: number;
  threshold: number;
  review_status: string;
  latest_review: Review | null;
};
type PatientIdentity = {
  id: string;
  first_name: string;
  last_name: string;
  medical_record_number: string;
};

type Queue = { items: Item[]; has_more: boolean; scope: string; notice: string };
type Props = {
  token: string;
  role: string;
  displayName: string;
  onUnauthorized: () => void;
};

const labels: Record<string, string> = {
  pending: 'Pending review',
  unreviewed: 'Not reviewed',
  needs_investigation: 'Needs investigation',
  confirmed_data_error: 'Confirmed data error',
  reviewed_no_correction_needed: 'Reviewed — no correction needed',
  all: 'All flagged scores',
};
function date(value: string) {
  return new Date(value).toLocaleString();
}

async function call<T>(
  path: string, token: string, unauthorized: () => void,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`/api${path}`, { ...options, headers });
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) unauthorized();
    let message = `Request failed (${response.status}).`;
    if (typeof data?.detail === 'string') message = data.detail;
    else if (Array.isArray(data?.detail)) {
      message = data.detail.map((entry: { msg?: string }) => entry.msg || 'Invalid input').join('; ');
    }
    throw new Error(message);
  }
  return data as T;
}

function ReviewPanel({ item, token, role, displayName, onUnauthorized, onSaved }:
  Props & { item: Item; onSaved: () => void }) {
  const [reviews, setReviews] = useState<Review[]>([]);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [saveError, setSaveError] = useState('');
  const [saved, setSaved] = useState('');
  const [status, setStatus] = useState<ReviewStatus>('needs_investigation');
  const [note, setNote] = useState('');
  const lock = useRef(false);
  const mounted = useRef(true);
  const unauthorized = useRef(onUnauthorized);
  unauthorized.current = onUnauthorized;
  const allowed = role === 'admin' || role === 'reviewer';

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setReviews([]);
    call<Review[]>(
      `/ml/anomaly-history/${item.history_id}/reviews?limit=21&offset=${offset}`,
      token, unauthorized.current, { signal: controller.signal },
    ).then(data => {
      if (!controller.signal.aborted) setReviews(data);
    }).catch(err => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Unable to load reviews.');
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [item.history_id, token, offset, refresh]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!allowed || lock.current || note.trim().length < 3) return;
    lock.current = true;
    setSaving(true); setSaveError(''); setSaved('');
    try {
      await call<Review>(`/ml/anomaly-history/${item.history_id}/reviews`,
        token, unauthorized.current, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ status, note: note.trim() }),
        });
      if (mounted.current) {
        setNote('');
        setSaved('Review saved to this scoring record.');
        setOffset(0); setRefresh(value => value + 1);
        onSaved();
      }
    } catch (err) {
      if (mounted.current) setSaveError(
        (err instanceof Error ? err.message : 'Unable to save review.') +
        ' If the connection was interrupted, refresh review history before resubmitting.',
      );
    } finally {
      lock.current = false;
      if (mounted.current) setSaving(false);
    }
  }

  return <section id="selected-review-evidence" className="rq-panel" tabIndex={-1}>
    <p className="eyebrow">SELECTED SCORING RECORD</p>
    <h3>Review the evidence. Record your decision.</h3>
    <dl className="rq-identifiers">
      <dt>Patient</dt>
      <dd>
        <strong>{item.patient_name || 'Patient name unavailable'}</strong>
        {item.medical_record_number && <div>Medical record number: {item.medical_record_number}</div>}
      </dd>
      <dt>Panel collected</dt><dd>{date(item.collected_at)}</dd>
      <dt>Scored</dt><dd>{date(item.scored_at)}</dd>
    </dl>
    <details className="pw-details">
      <summary>Technical details</summary>
      <dl className="rq-identifiers">
        <dt>Patient ID</dt><dd>{item.patient_id}</dd>
        <dt>Visit ID</dt><dd>{item.encounter_id}</dd>
        <dt>Score ID</dt><dd>{item.history_id}</dd>
        <dt>Model version</dt><dd>{item.model_version}</dd>
        <dt>Scoring version</dt><dd>{item.scoring_version}</dd>
      </dl>
    </details>
    <div className="pw-score-numbers">
      <div><small>Anomaly score</small><strong>{item.anomaly_score.toFixed(4)}</strong></div>
      <div><small>Threshold</small><strong>{item.threshold.toFixed(4)}</strong></div>
    </div>
    <p className="pw-notice">This review applies only to the selected saved result. It does not change lab values or establish a diagnosis. Inspect the historical panel below before deciding.</p>

    <SavedPanel
      historyId={item.history_id}
      token={token}
      onUnauthorized={onUnauthorized}
    />
    {allowed ? <form className="rq-form" onSubmit={submit}>
      <p className="pw-small">Submitting as {displayName}. Attribution comes from your signed-in account.</p>
      <label htmlFor="review-status">Review decision</label>
      <select id="review-status" value={status} disabled={saving}
        onChange={event => setStatus(event.target.value as ReviewStatus)}>
        {(['needs_investigation', 'confirmed_data_error', 'reviewed_no_correction_needed'] as ReviewStatus[])
          .map(value => <option key={value} value={value}>{labels[value]}</option>)}
      </select>
      <label htmlFor="review-note">Reason and supporting observations</label>
      <textarea id="review-note" value={note} required minLength={3} maxLength={5000}
        disabled={saving} placeholder="Explain what you reviewed and why you chose this decision…"
        onChange={event => setNote(event.target.value)} />
      <div className="pw-row">
        <span className="pw-small">Creates a new review; earlier reviews remain available.</span>
        <button className="button primary" disabled={saving || note.trim().length < 3}>
          {saving ? 'Saving review…' : 'Save review'}
        </button>
      </div>
    </form> : <p className="pw-notice">Your account can view reviews. Submission requires an admin or reviewer role.</p>}
    {saved && <p className="pw-notice" role="status">{saved}</p>}
    {saveError && <p className="error-box" role="alert">{saveError}</p>}

    <div className="pw-row rq-history-heading"><h3>Review history</h3>
      <button className="button secondary" disabled={loading || saving}
        onClick={() => setRefresh(value => value + 1)}>↻ Refresh history</button>
    </div>
    {loading ? <p className="pw-small" role="status">Loading reviews…</p>
      : error ? <p className="error-box" role="alert">{error}</p>
      : reviews.length === 0 ? <p className="pw-small">No reviews on this page.</p>
      : reviews.slice(0, 20).map(review => <article className="rq-history-card" key={review.id}>
        <div className="pw-row"><strong>{labels[review.status]}</strong><span className="pw-small">{date(review.created_at)}</span></div>
        <p className="pw-prose">{review.note}</p>
        <p className="pw-small">{review.reviewer_name} · {review.reviewer_user_id ? 'Account-linked review' : 'Legacy self-reported name'}</p>
      </article>)}
    <div className="pw-pager">
      <span>Review history · Page {offset / 20 + 1}</span>
      <div><button className="button secondary" disabled={loading || saving || offset === 0} onClick={() => setOffset(offset - 20)}>← Previous</button>
        <button className="button secondary" disabled={loading || saving || reviews.length <= 20} onClick={() => setOffset(offset + 20)}>Next →</button></div>
    </div>
  </section>;
}

export default function ReviewQueue(props: Props) {
  const [filter, setFilter] = useState('pending');
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState<Queue | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState<Item | null>(null);
  const unauthorized = useRef(props.onUnauthorized);

  useEffect(() => {
    if (!selected) return;
    const frame = requestAnimationFrame(() => {
      const panel = document.getElementById('selected-review-evidence');
      if (panel) {
        panel.focus({ preventScroll: true });
        panel.scrollIntoView({
          behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches
            ? 'auto' : 'smooth',
          block: 'start',
        });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [selected?.history_id]);
  unauthorized.current = props.onUnauthorized;

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(''); setData(null);
    call<Queue>(
      `/ml/review-queue?status=${filter}&limit=20&offset=${offset}`,
      props.token, unauthorized.current, { signal: controller.signal },
    ).then(async result => {
      // Patient identity enrichment v1
      // Fetch each distinct patient once per queue load.
      const ids = [...new Set(result.items.map(item => item.patient_id))];
      const identities = new Map<string, PatientIdentity>();

      await Promise.all(ids.map(async id => {
        try {
          const patient = await call<PatientIdentity>(
            `/patients/${encodeURIComponent(id)}`,
            props.token,
            unauthorized.current,
            { signal: controller.signal },
          );
          if (
            patient.id === id &&
            typeof patient.first_name === 'string' &&
            typeof patient.last_name === 'string' &&
            typeof patient.medical_record_number === 'string'
          ) {
            identities.set(id, patient);
          }
        } catch {
          // Keep scoring evidence available if a patient lookup fails.
          // Authentication failures are handled by call().
        }
      }));

      if (!controller.signal.aborted) {
        setData({
          ...result,
          items: result.items.map(item => {
            const patient = identities.get(item.patient_id);
            return {
              ...item,
              patient_name: patient
                ? `${patient.first_name} ${patient.last_name}`.trim()
                : undefined,
              medical_record_number: patient?.medical_record_number,
              patient_lookup_failed: !patient,
            };
          }),
        });
      }
    }).catch(err => {
      if (!controller.signal.aborted) setError(err instanceof Error ? err.message : 'Unable to load queue.');
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [filter, offset, refresh, props.token]);

  return <section id="review-queue" className="rq-shell">
    <header className="rq-heading">
      <div><p className="eyebrow">HUMAN-LED REVIEW</p><h2>From a flag to a considered decision.</h2>
        <p className="muted">Review flagged scoring records and preserve the decision history.</p></div>
      <span className="rq-access-label">Signed in as {props.displayName} · {props.role}</span>
    </header>
    <div className="rq-toolbar">
      <div><label htmlFor="queue-filter">Show scoring records</label>
        <select id="queue-filter" value={filter} onChange={event => {
          setFilter(event.target.value); setOffset(0);
        }}>{Object.entries(labels).map(([value, text]) => <option key={value} value={value}>{text}</option>)}</select>
      </div>
      <button className="button secondary" disabled={loading} onClick={() => setRefresh(v => v + 1)}>↻ Refresh queue</button>
    </div>
    {loading ? <div className="state-box" role="status">Loading flagged scores…</div>
      : error ? <p className="error-box" role="alert">{error}</p>
      : !data?.items.length ? <div className="state-box">No flagged scoring records match this filter on this page.</div>
      : <div className="table-scroll"><table>
        <thead><tr><th>Patient / scoring record</th><th>Score / threshold</th><th>Review status</th><th>Latest reviewer</th><th>Action</th></tr></thead>
        <tbody>{data.items.map(item => <tr key={item.history_id}
          className={selected?.history_id === item.history_id ? 'rq-selected-row' : ''}>
          <td className="rq-patient-cell">
            <strong>{item.patient_name || 'Patient name unavailable'}</strong>
            <small>{item.medical_record_number
              ? `MRN: ${item.medical_record_number}`
              : 'Medical record number unavailable'}</small>
            <small>Scored: {date(item.scored_at)}</small>
            <small>Collected: {date(item.collected_at)}</small>

          </td>
          <td>{item.anomaly_score.toFixed(4)} / {item.threshold.toFixed(4)}</td>
          <td><span className="pw-badge">{labels[item.review_status] || item.review_status}</span></td>
          <td>{item.latest_review?.reviewer_name || 'Not recorded'}</td>
          <td><button className="record-button"
              aria-label={`Review scoring record for ${item.patient_name || item.patient_id}`}
              aria-controls="selected-review-evidence"
              aria-expanded={selected?.history_id === item.history_id}
              onClick={() => setSelected(item)}>
              {selected?.history_id === item.history_id ? 'Selected ✓' : 'Inspect & review ↗'}
            </button></td>
        </tr>)}</tbody>
      </table></div>}
    <div className="pagination">
      <span>{data?.items.length || 0} on this page · Page {offset / 20 + 1}</span>
      <div><button className="button secondary" disabled={loading || offset === 0} onClick={() => setOffset(offset - 20)}>← Previous</button>
        <button className="button secondary" disabled={loading || !data?.has_more} onClick={() => setOffset(offset + 20)}>Next →</button></div>
    </div>
    {data?.items.some(item => item.patient_lookup_failed) &&
      <p className="pw-notice" role="status">
        Some patient names could not be loaded. Their identifiers and scoring
        records remain visible. Refresh the queue to retry.
      </p>}
    <p className="rq-scope">{data?.scope || 'Flagged scoring-history records. Repeated scores are separate entries.'}</p>
    {selected && <>
      <div className="rq-close"><button className="button secondary" onClick={() => setSelected(null)}>Close selected review ×</button></div>
      <ReviewPanel key={selected.history_id} {...props} item={selected}
        onSaved={() => setRefresh(value => value + 1)} />
    </>}
  </section>;
}
