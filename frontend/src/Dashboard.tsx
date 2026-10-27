import { useEffect, useRef, useState } from 'react';
import './dashboard-overview.css';

type Props = {
  token: string;
  name: string;
  navigate: (page: string) => void;
  onUnauthorized: () => void;
};

type Counts = {
  patients: number;
  encounters: number;
  lab_results: number;
  scoring_records: number;
  pending_reviews: number;
};

type Person = {
  patient_id: string;
  patient_name: string;
  medical_record_number: string;
};

type Encounter = Person & {
  encounter_id: string;
  visited_at: string;
  reason: string;
};

type Score = Person & {
  history_id: string;
  encounter_id: string;
  scored_at: string;
  collected_at: string;
  anomaly_score: number;
  threshold: number;
  flagged_for_review: boolean;
  review_status: string;
  model_version: string;
  scoring_version: string;
};

type Activity = {
  generated_at: string;
  recent_encounters: Encounter[];
  recent_scores: Score[];
  pending_reviews: Score[];
  scope: string;
};

const dateText = (value: string) => {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString(
    undefined,
    { dateStyle: 'medium', timeStyle: 'short' },
  );
};

const numberText = (value: number) =>
  Number.isFinite(value)
    ? value.toLocaleString(undefined, { maximumFractionDigits: 3 })
    : 'Unavailable';

const statusText = (value: string) => value.replaceAll('_', ' ');

export default function Dashboard({
  token, name, navigate, onUnauthorized,
}: Props) {
  const [totals, setTotals] = useState<Counts | null>(null);
  const [scope, setScope] = useState('');
  const [activity, setActivity] = useState<Activity | null>(null);
  const [errors, setErrors] = useState<string[]>([]);
  const [busy, setBusy] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const unauthorized = useRef(onUnauthorized);
  unauthorized.current = onUnauthorized;

  useEffect(() => {
    const controller = new AbortController();
    let expired = false;
    setBusy(true);
    setErrors([]);
    setTotals(null);
    setActivity(null);

    async function get(path: string) {
      const response = await fetch('/api' + path, {
        headers: { Authorization: `Bearer ${token}` },
        signal: controller.signal,
      });
      if (response.status === 401) {
        if (!expired && !controller.signal.aborted) {
          expired = true;
          unauthorized.current();
        }
        throw new Error('Your session expired.');
      }
      const body = await response.json().catch(() => null);
      if (!response.ok) {
        throw new Error(
          typeof body?.detail === 'string'
            ? body.detail
            : `Request failed (${response.status}).`,
        );
      }
      return body;
    }

    async function load() {
      const results = await Promise.allSettled([
        get('/dashboard'),
        get('/dashboard/activity'),
      ]);
      if (controller.signal.aborted || expired) return;

      const problems: string[] = [];
      const countsResult = results[0];
      if (countsResult.status === 'fulfilled') {
        const body = countsResult.value;
        const keys = [
          'patients', 'encounters', 'lab_results',
          'scoring_records', 'pending_reviews',
        ];
        if (body?.counts && keys.every(
          key => Number.isSafeInteger(body.counts[key]) && body.counts[key] >= 0,
        )) {
          setTotals(body.counts);
          setScope(typeof body.scope === 'string' ? body.scope : '');
        } else {
          problems.push('Database totals returned an unexpected format.');
        }
      } else {
        problems.push(`Totals: ${String(countsResult.reason)}`);
      }

      const activityResult = results[1];
      if (activityResult.status === 'fulfilled') {
        const body = activityResult.value;
        if (
          body &&
          Array.isArray(body.recent_encounters) &&
          Array.isArray(body.recent_scores) &&
          Array.isArray(body.pending_reviews)
        ) {
          setActivity(body);
        } else {
          problems.push('Recent activity returned an unexpected format.');
        }
      } else {
        problems.push(`Activity: ${String(activityResult.reason)}`);
      }
      setErrors(problems);
      setBusy(false);
    }

    void load();
    return () => controller.abort();
  }, [token, refresh]);

  const metrics: { key: keyof Counts; title: string; caption: string }[] = [
    { key: 'patients', title: 'Patients', caption: 'Saved patient records' },
    { key: 'encounters', title: 'Encounters', caption: 'Recorded visits' },
    { key: 'lab_results', title: 'Measurements', caption: 'Individual lab results' },
    { key: 'scoring_records', title: 'Saved scores', caption: 'Scoring-history records' },
    { key: 'pending_reviews', title: 'Pending reviews', caption: 'Flagged scores awaiting action' },
  ];

  const empty = (message: string) => <p className="ov-empty">{message}</p>;

  return <section className="ov-page" aria-busy={busy}>
    <header className="ov-heading">
      <div>
        <p className="ov-eyebrow">INTELLICDM / WORKSPACE OVERVIEW</p>
        <h1>Hello, {name.trim().split(/\s+/)[0] || 'there'}<span>.</span></h1>
        <p>Your records, model results and review activity in one place.</p>
      </div>
      <button className="ov-button ov-outline" disabled={busy}
        onClick={() => setRefresh(value => value + 1)}>
        {busy ? 'Refreshing…' : '↻ Refresh dashboard'}
      </button>
    </header>

    <section className="ov-hero">
      <div>
        <span className="ov-label">FROM RECORDS TO UNDERSTANDING</span>
        <h2>A clearer view.<br /><em>A better starting point.</em></h2>
        <p>Explore patient histories, test chemistry panels and follow up on
          results that need a closer look.</p>
        <div className="ov-hero-actions">
          <button className="ov-button ov-mint"
            onClick={() => navigate('patients')}>Explore patients ↗</button>
          <button className="ov-button ov-glass"
            onClick={() => navigate('csv')}>Analyze a CSV →</button>
        </div>
      </div>
      <div className="ov-hero-note">
        <span className="ov-orbit" aria-hidden="true">✳</span>
        <strong>Traceable by design</strong>
        <p>Saved measurements. Source-linked answers.<br />Human review.</p>
      </div>
    </section>

    {errors.map(message =>
      <p className="ov-error" role="alert" key={message}>{message}</p>,
    )}

    <div className="ov-metrics">
      {metrics.map(({ key, title, caption }) =>
        <article key={key} className={key === 'pending_reviews' ? 'ov-attention' : ''}>
          <p>{title}</p>
          <strong>{totals ? totals[key].toLocaleString() : '—'}</strong>
          <small>{busy ? 'Loading…' : totals ? caption : 'Count unavailable'}</small>
        </article>,
      )}
    </div>

    {totals && <p className="ov-footnote">{scope}</p>}

    <div className="ov-shortcuts">
      {[
        ['patients', '01', 'Patient directory', 'Records, encounters and AI assistance'],
        ['csv', '02', 'CSV analysis', 'Upload, validate, score and export'],
        ['reviews', '03', 'Review queue', 'Inspect evidence and record a decision'],
      ].map(([page, index, title, description]) =>
        <button key={page} onClick={() => navigate(page)}>
          <span className="ov-shortcut-number">{index}</span>
          <span><strong>{title}</strong><small>{description}</small></span>
          <span aria-hidden="true">↗</span>
        </button>,
      )}
    </div>

    {busy && <p className="ov-empty" role="status">Loading saved activity…</p>}

    {activity && <>
      <div className="ov-grid">
        <section className="ov-card">
          <header>
            <div><p className="ov-eyebrow">PATIENT ACTIVITY</p>
              <h2>Recent encounters</h2></div>
            <button className="ov-link" onClick={() => navigate('patients')}>
              Patient directory ↗
            </button>
          </header>
          <p className="ov-card-caption">Five latest visits by encounter date.</p>
          {activity.recent_encounters.length === 0
            ? empty('No encounters have been saved yet.')
            : <div className="ov-visit-list">
              {activity.recent_encounters.map(item =>
                <article key={item.encounter_id} className="ov-visit">
                  <div className="ov-avatar" aria-hidden="true">
                    {item.patient_name.trim().slice(0, 1).toUpperCase()}
                  </div>
                  <div>
                    <strong>{item.patient_name}</strong>
                    <small>{item.medical_record_number}</small>
                    <p>{item.reason}</p>
                    <time dateTime={item.visited_at}>{dateText(item.visited_at)}</time>
                  </div>
                </article>,
              )}
            </div>}
        </section>

        <section className="ov-card">
          <header>
            <div><p className="ov-eyebrow">HUMAN REVIEW</p>
              <h2>Needs attention</h2></div>
            <button className="ov-link" onClick={() => navigate('reviews')}>
              Open queue ↗
            </button>
          </header>
          <p className="ov-card-caption">
            Up to five pending flagged scoring records.
          </p>
          {activity.pending_reviews.length === 0
            ? empty('No flagged scores currently await review.')
            : activity.pending_reviews.map(item =>
              <article className="ov-pending" key={item.history_id}>
                <div className="ov-row">
                  <strong>{item.patient_name}</strong>
                  <span className="ov-badge ov-amber">
                    {statusText(item.review_status)}
                  </span>
                </div>
                <small>{item.medical_record_number}</small>
                <p>Score <b>{numberText(item.anomaly_score)}</b>
                  <span> · threshold {numberText(item.threshold)}</span></p>
                <time dateTime={item.scored_at}>{dateText(item.scored_at)}</time>
                <details>
                  <summary>Technical details</summary>
                  <p className="ov-id">Score: {item.history_id}</p>
                  <p className="ov-id">Encounter: {item.encounter_id}</p>
                </details>
              </article>,
            )}
        </section>
      </div>

      <section className="ov-card ov-scores">
        <header>
          <div><p className="ov-eyebrow">MODEL ACTIVITY</p>
            <h2>Recent saved scores</h2></div>
          <span className="ov-badge ov-neutral">Latest 5 records</span>
        </header>
        <p className="ov-card-caption">
          Historical results from saved encounter scoring. CSV test runs are separate.
        </p>
        {activity.recent_scores.length === 0
          ? empty('Score a saved encounter from a patient workspace to see it here.')
          : <div className="ov-table-wrap">
            <table>
              <thead><tr>
                <th>Patient</th><th>Scored</th><th>Score / threshold</th>
                <th>Review flag</th><th>Review status</th>
              </tr></thead>
              <tbody>{activity.recent_scores.map(item =>
                <tr key={item.history_id}>
                  <td><strong>{item.patient_name}</strong>
                    <small>{item.medical_record_number}</small></td>
                  <td>{dateText(item.scored_at)}</td>
                  <td><strong>{numberText(item.anomaly_score)}</strong>
                    <small>Threshold {numberText(item.threshold)}</small></td>
                  <td><span className={`ov-badge ${item.flagged_for_review
                    ? 'ov-amber' : 'ov-neutral'}`}>
                    {item.flagged_for_review ? 'Flagged' : 'Not flagged'}
                  </span></td>
                  <td>{statusText(item.review_status)}</td>
                </tr>,
              )}</tbody>
            </table>
          </div>}
      </section>

      <div className="ov-update">
        <span>Activity loaded {dateText(activity.generated_at)} · Times shown in your browser’s timezone.</span>
        <p>{activity.scope}</p>
      </div>
    </>}

    <aside className="ov-notice">
      <strong>Development workspace</strong>
      <p>Synthetic-data prototype. Flags indicate a need for review, not a diagnosis.
        An unflagged result does not establish clinical normality.
        Generated answers must be checked against their sources.</p>
    </aside>
  </section>;
}
