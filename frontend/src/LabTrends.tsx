import { useEffect, useRef, useState } from 'react';

type Point = {
  lab_id: string;
  encounter_id: string;
  collected_at: string;
  value: string;
};
type Series = {
  unit: string;
  points: Point[];
  distinct_collection_times: number;
  conflicting_same_time_values: boolean;
  latest_minus_earliest: string | number | null;
  change_unavailable_reason?: string | null;
};
type Trend = {
  patient_id: string;
  feature: string;
  returned_lab_rows: number;
  truncated: boolean;
  selection: string;
  series_by_unit: Series[];
  notice: string;
};
type Props = {
  patientId: string;
  token: string;
  onUnauthorized: () => void;
};

const features = [
  ['glucose', 'Glucose'],
  ['creatinine', 'Creatinine'],
  ['urea_nitrogen', 'Urea nitrogen'],
  ['sodium', 'Sodium'],
  ['potassium', 'Potassium'],
  ['chloride', 'Chloride'],
  ['calcium', 'Calcium'],
  ['total_co2', 'Total CO₂'],
];

function dateTime(value: string) {
  return new Date(value).toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
  });
}

function shortDate(value: number) {
  return new Date(value).toLocaleDateString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

function SeriesCard({ series, name }: { series: Series; name: string }) {
  const [active, setActive] = useState<string | null>(null);
  const points = [...series.points].sort((a, b) =>
    Date.parse(a.collected_at) - Date.parse(b.collected_at) ||
    a.lab_id.localeCompare(b.lab_id)
  );
  const numeric = points.flatMap(point => {
    const time = Date.parse(point.collected_at);
    const value = Number(point.value);
    return point.value.trim() !== '' && Number.isFinite(value) && Number.isFinite(time)
      ? [{ point, time, value }] : [];
  });
  const selected = points.find(point => point.lab_id === active);
  const width = 820;
  const height = 280;
  const left = 80;
  const right = 790;
  const top = 25;
  const bottom = 225;
  const times = numeric.map(item => item.time);
  const values = numeric.map(item => item.value);
  const minTime = numeric.length ? Math.min(...times) : 0;
  const maxTime = numeric.length ? Math.max(...times) : 0;
  const minValue = numeric.length ? Math.min(...values) : 0;
  const maxValue = numeric.length ? Math.max(...values) : 0;
  const pad = (maxValue - minValue) * 0.15 || Math.abs(minValue) * 0.05 || 1;
  const low = minValue - pad;
  const high = maxValue + pad;
  const x = (time: number) => minTime === maxTime
    ? (left + right) / 2
    : left + (time - minTime) / (maxTime - minTime) * (right - left);
  const y = (value: number) => bottom - (value - low) / (high - low) * (bottom - top);
  const path = numeric.map(item => `${x(item.time)},${y(item.value)}`).join(' ');
  const change = series.latest_minus_earliest;
  const changeText = change === null
    ? 'Unavailable'
    : `${Number(change) > 0 ? '+' : ''}${change} ${series.unit}`;

  return <article className="lt-card">
    <header className="pw-row">
      <div>
        <p className="eyebrow">RECORDED MEASUREMENTS</p>
        <h3>{name} <span className="lt-unit">{series.unit}</span></h3>
      </div>
      <span className="pw-badge">{points.length} saved rows</span>
    </header>

    <div className="lt-metrics">
      <div><small>Collection times</small><strong>{series.distinct_collection_times}</strong></div>
      <div><small>Latest minus earliest · returned data</small><strong>{changeText}</strong></div>
    </div>

    {series.change_unavailable_reason &&
      <p className="pw-small">{series.change_unavailable_reason}</p>}
    {series.conflicting_same_time_values &&
      <p className="pw-notice">Different values share a collection time. Points are shown without a connecting line; inspect the source rows.</p>}

    {numeric.length > 0 ? <div className="lt-chart-scroll">
      <svg className="lt-chart" viewBox={`0 0 ${width} ${height}`}
        role="group" aria-label={`${name} in ${series.unit}. Exact values are listed in the table below.`}>
        <title>{name} by collection time</title>
        <desc>The vertical axis is fitted to the returned values. Connecting lines are visual guides, not measured values between samples.</desc>
        {[0, 1, 2, 3, 4].map(index => {
          const value = low + (high - low) * index / 4;
          return <g key={index}>
            <line x1={left} x2={right} y1={y(value)} y2={y(value)}
              stroke="#e4edf0" strokeDasharray="4 5" />
            <text x={left - 12} y={y(value) + 4} textAnchor="end" className="lt-axis">
              {Number(value.toPrecision(4))}
            </text>
          </g>;
        })}
        {!series.conflicting_same_time_values && numeric.length > 1 &&
          <polyline points={path} fill="none" stroke="#168879" strokeWidth="3"
            strokeLinejoin="round" strokeLinecap="round" />}
        {numeric.map(({ point, time, value }) =>
          <circle key={point.lab_id} cx={x(time)} cy={y(value)}
            r={active === point.lab_id ? 7 : 5}
            fill={active === point.lab_id ? '#102c3e' : '#168879'}
            stroke="white" strokeWidth="2" tabIndex={0} role="button"
            aria-label={`${point.value} ${series.unit}, ${dateTime(point.collected_at)}`}
            onMouseEnter={() => setActive(point.lab_id)}
            onFocus={() => setActive(point.lab_id)}
            onClick={() => setActive(point.lab_id)}
            onKeyDown={event => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault(); setActive(point.lab_id);
              }
            }}>
            <title>{point.value} {series.unit} · {dateTime(point.collected_at)}</title>
          </circle>
        )}
        <text x={minTime === maxTime ? (left + right) / 2 : left}
          y={258} textAnchor={minTime === maxTime ? 'middle' : 'start'}
          className="lt-axis">{shortDate(minTime)}</text>
        {minTime !== maxTime &&
          <text x={right} y={258} textAnchor="end" className="lt-axis">{shortDate(maxTime)}</text>}
      </svg>
    </div> : <p className="state-box">No plottable numeric values. Inspect the saved rows below.</p>}

    <div className="lt-point" aria-live="polite">
      {selected
        ? <><strong>{selected.value} {series.unit}</strong><span>{dateTime(selected.collected_at)}</span></>
        : <span>Select or focus a point to inspect its recorded value.</span>}
    </div>
    <p className="pw-small">
      Collection times use your browser’s timezone. The vertical axis is fitted to the data.
      Lines only connect saved measurements.
      {numeric.length !== points.length && ' Some rows could not be plotted; all returned rows remain listed below.'}
    </p>

    <details className="pw-details">
      <summary>View all {points.length} saved rows and source identifiers</summary>
      <div className="table-scroll">
        <table>
          <thead><tr><th>Collected</th><th>Stored value</th><th>Source records</th></tr></thead>
          <tbody>{points.map(point => <tr key={point.lab_id}>
            <td>{dateTime(point.collected_at)}</td>
            <td><strong>{point.value}</strong> {series.unit}</td>
            <td><small className="lt-id">Lab: {point.lab_id}<br />Encounter: {point.encounter_id}</small></td>
          </tr>)}</tbody>
        </table>
      </div>
    </details>
  </article>;
}

export default function LabTrends({ patientId, token, onUnauthorized }: Props) {
  const [feature, setFeature] = useState('glucose');
  const [data, setData] = useState<Trend | null>(null);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const unauthorized = useRef(onUnauthorized);
  unauthorized.current = onUnauthorized;

  useEffect(() => {
    const controller = new AbortController();
    setBusy(true); setData(null); setError('');
    async function load() {
      try {
        const response = await fetch(
          `/api/ai/patients/${patientId}/lab-trends/${feature}`,
          { headers: { Authorization: `Bearer ${token}` }, signal: controller.signal },
        );
        const body = await response.json().catch(() => null);
        if (controller.signal.aborted) return;
        if (response.status === 401) {
          unauthorized.current();
          throw new Error('Your session has expired. Sign in again.');
        }
        if (!response.ok) throw new Error(
          typeof body?.detail === 'string' ? body.detail : `Request failed (${response.status}).`
        );
        if (body?.patient_id !== patientId || body?.feature !== feature ||
            !Array.isArray(body?.series_by_unit)) {
          throw new Error('The trend response did not match this patient and measurement.');
        }
        setData(body as Trend);
      } catch (err) {
        if (!controller.signal.aborted)
          setError(err instanceof Error ? err.message : 'Trends could not be loaded.');
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }
    void load();
    return () => controller.abort();
  }, [patientId, token, feature, refresh]);

  const name = features.find(item => item[0] === feature)?.[1] || feature;

  return <section className="lt-shell" aria-label="Patient lab trends">
    <div className="lt-heading">
      <div>
        <p className="eyebrow">MEASUREMENTS OVER TIME</p>
        <h2>A clearer view of the record.</h2>
        <p className="muted">Explore saved measurements across this patient’s encounters.</p>
      </div>
      <button className="button secondary" disabled={busy}
        onClick={() => setRefresh(value => value + 1)}>↻ Refresh</button>
    </div>
    <div className="lt-controls">
      <label htmlFor="trend-measurement">Measurement</label>
      <select id="trend-measurement" value={feature} onChange={event => setFeature(event.target.value)}>
        {features.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select>
      <span className="pw-small">Each unit is displayed separately. No unit conversion.</span>
    </div>

    {busy ? <p role="status" className="state-box">Loading saved measurements…</p>
      : error ? <p role="alert" className="error-box">{error}</p>
      : data && <>
        <p className="pw-small">{data.selection} · {data.returned_lab_rows} returned rows</p>
        {data.truncated && <p className="pw-notice">
          Older matching rows were omitted by the backend. Charts and changes cover only the returned subset.
        </p>}
        {data.series_by_unit.every(series => series.points.length === 0)
          ? <div className="state-box">No saved {name.toLowerCase()} measurements were returned for this patient.</div>
          : data.series_by_unit.filter(series => series.points.length > 0).map(series =>
            <SeriesCard key={`${feature}:${series.unit}:${refresh}`} series={series} name={name} />)}
        <p className="pw-notice">{data.notice || 'Stored measurements only. A numerical change is not a clinical interpretation.'}</p>
      </>}
  </section>;
}
