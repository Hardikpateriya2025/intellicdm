import { useEffect, useRef, useState } from 'react';
import SavePatientRecords from './SavePatientRecords';

const FEATURES = [
  'glucose', 'creatinine', 'urea_nitrogen', 'sodium',
  'potassium', 'chloride', 'calcium', 'total_co2',
];

type Row = {
  row_number: number;
  case_id: string;
  values: Record<string, string>;
  validation_errors: string[];
};

type Preview = {
  rows: Row[];
  row_count: number;
  valid_count: number;
  ignored_columns: string[];
  notice: string;
};

type Score = {
  anomaly_score: number;
  threshold: number;
  flagged_for_review: boolean;
  ml_flagged: boolean;
  largest_error_feature: string;
  data_quality_issues: string[];
  model_version: string;
  scoring_version: string;
  interpretation: string;
};

type Result = {
  row_number: number;
  status: 'scored' | 'invalid';
  result?: Score;
  errors?: string[];
};

type Props = { token: string; onUnauthorized: () => void };

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], {type:'text/csv;charset=utf-8'}));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function csvCell(value: unknown) {
  let text = value == null ? '' : String(value);
  // Escape spreadsheet formulas in textual fields.
  if (typeof value === 'string' && /^[\s]*[=+\-@]/.test(text)) text = "'" + text;
  return '"' + text.replaceAll('"', '""') + '"';
}

export default function CsvTesting({token,onUnauthorized}: Props) {
  const [preview,setPreview] = useState<Preview|null>(null);
  const [originalFile,setOriginalFile] = useState<File|null>(null);
  const [filename,setFilename] = useState('');
  const [results,setResults] = useState<Result[]>([]);
  const [busy,setBusy] = useState(false);
  const [phase,setPhase] = useState('');
  const [error,setError] = useState('');
  const [confirmed,setConfirmed] = useState(false);
  const [filter,setFilter] = useState('all');
  const [page,setPage] = useState(0);
  const [selected,setSelected] = useState<Result|null>(null);

  const running = useRef<AbortController|null>(null);
  useEffect(() => () => running.current?.abort(), []);

  async function request<T>(path:string, options:RequestInit, signal:AbortSignal):Promise<T> {
    const headers = new Headers(options.headers);
    headers.set('Authorization',`Bearer ${token}`);
    const response = await fetch(`/api${path}`,{...options,headers,signal});
    const body = await response.json().catch(() => null);
    if (response.status === 401) onUnauthorized();
    if (!response.ok) {
      throw new Error(
        typeof body?.detail === 'string'
          ? body.detail
          : `Request failed (${response.status}).`,
      );
    }
    return body as T;
  }

  async function upload(file:File) {
    if (running.current) return;
    setError(''); setPreview(null); setResults([]);
    setOriginalFile(null);
    setSelected(null); setConfirmed(false); setPage(0);
    setFilename(file.name);
    if (file.size > 2 * 1024 * 1024) {
      setError('Choose a CSV no larger than 2 MiB.');
      return;
    }
    const controller = new AbortController();
    running.current = controller;
    setBusy(true); setPhase('Reading and validating CSV…');
    try {
      const form = new FormData();
      form.append('file',file);
      const data = await request<Preview>(
        '/ml/csv/preview',{method:'POST',body:form},controller.signal,
      );
      if (!controller.signal.aborted) {
        setPreview(data);
        setOriginalFile(file);
        setPhase('Preview ready. Confirm units before scoring.');
      }
    } catch (err) {
      if (!controller.signal.aborted)
        setError(err instanceof Error ? err.message : 'Upload failed.');
    } finally {
      if (running.current === controller) running.current = null;
      setBusy(false);
    }
  }

  async function score() {
    if (!preview || !confirmed || running.current) return;
    const controller = new AbortController();
    running.current = controller;
    setBusy(true); setError(''); setResults([]);
    setSelected(null); setFilter('all'); setPage(0);
    const completed:Result[] = [];
    try {
      for (let index=0; index<preview.rows.length; index+=25) {
        if (controller.signal.aborted) break;
        setPhase(`Scoring records ${index+1}–${Math.min(index+25,preview.rows.length)}…`);
        const rows = preview.rows.slice(index,index+25).map(row => ({
          row_number:row.row_number, values:row.values,
        }));
        const response = await request<{rows:Result[]}>(
          '/ml/csv/score',
          {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body:JSON.stringify({rows}),
          },
          controller.signal,
        );
        if (controller.signal.aborted) break;
        completed.push(...response.rows);
        setResults([...completed]);
      }
      setPhase(controller.signal.aborted
        ? 'Stopped. Completed batches remain available.'
        : 'Analysis complete.');
    } catch (err) {
      if (controller.signal.aborted) {
        setPhase('Stopped. Completed batches remain available.');
      } else {
        setPhase('Analysis interrupted. Completed batches remain available.');
        setError(err instanceof Error ? err.message : 'Scoring failed.');
      }
    } finally {
      if (running.current === controller) running.current = null;
      setBusy(false);
    }
  }

  function exportResults() {
    if (!preview) return;
    const byNumber = new Map(results.map(row => [row.row_number,row]));
    const header = [
      'row_number','case_id',...FEATURES,'status',
      'flagged_for_review','ml_flagged','anomaly_score','threshold',
      'largest_error_feature','data_quality_issues','errors',
      'model_version','scoring_version',
    ];
    const records = preview.rows.map(row => {
      const item = byNumber.get(row.row_number);
      const score = item?.result;
      return [
        row.row_number,row.case_id,...FEATURES.map(key => row.values[key]),
        item?.status || 'not_processed',
        score?.flagged_for_review,score?.ml_flagged,
        score?.anomaly_score,score?.threshold,score?.largest_error_feature,
        score?.data_quality_issues.join('; '),item?.errors?.join('; '),
        score?.model_version,score?.scoring_version,
      ];
    });
    download('intellicdm-csv-results.csv',
      [header,...records].map(row=>row.map(csvCell).join(',')).join('\r\n'));
  }

  const scored = results.filter(row=>row.status==='scored');
  const flagged = scored.filter(row=>row.result?.flagged_for_review);
  const invalid = results.filter(row=>row.status==='invalid');
  const visible = results.filter(row =>
    filter==='all' ||
    (filter==='flagged' && row.result?.flagged_for_review) ||
    (filter==='unflagged' && row.status==='scored' && !row.result?.flagged_for_review) ||
    (filter==='invalid' && row.status==='invalid'),
  );
  const sourceRows = new Map(preview?.rows.map(row=>[row.row_number,row]) || []);
  const progress = preview ? results.length / preview.row_count * 100 : 0;

  return <section>
    <header className="page-heading">
      <div>
        <p className="eyebrow">BATCH ANOMALY EXPLORATION</p>
        <h1>From rows to review<span>.</span></h1>
        <p className="muted">Upload chemistry panels. Inspect every result. Download the evidence.</p>
      </div>
      <button className="button secondary" onClick={()=>download(
        'chemistry-template.csv',
        FEATURES.join(',')+'\n100,0.9,14,140,4.2,103,9.5,25\n',
      )}>↓ CSV template</button>
    </header>

    <div className="csv-upload">
      <span className="csv-upload-icon" aria-hidden="true">⇧</span>
      <h2>Bring your chemistry data.</h2>
      <p>CSV file · maximum file size 2 MB · up to 2,000 rows for analysis</p>
      <label className="button primary">
        Choose CSV file
        <input type="file" accept=".csv,text/csv" disabled={busy}
          onChange={event=>{
            const file=event.target.files?.[0];
            event.target.value='';
            if(file) void upload(file);
          }} />
      </label>
      {filename && <p className="csv-filename">{filename}</p>}
    </div>

    <div className="csv-units">
      <strong>Required input units</strong>
      <p>Glucose, creatinine, urea nitrogen, calcium: <b>mg/dL</b></p>
      <p>Sodium, potassium, chloride, total CO₂: <b>mmol/L</b></p>
      <small>One row = one complete eight-measurement panel. Units are not inferred or converted.</small>
    </div>

    {error && <p role="alert" className="error-box">{error}</p>}
    {phase && <p role="status" className="pw-notice">{phase}</p>}

    {preview && <>
      <div className="dash-stats">
        {[
          ['Uploaded rows',preview.row_count],
          ['Processed',results.length],
          ['Flagged for review',flagged.length],
          ['Invalid results',invalid.length],
        ].map(([label,value])=><article key={label}>
          <small>{label}</small><strong>{value}</strong>
        </article>)}
      </div>

      <p className="pw-small">
        {preview.valid_count} rows passed initial numeric validation.
        {' '}{preview.row_count-preview.valid_count} rows have validation errors.
        {preview.ignored_columns.length>0 &&
          ` Extra columns excluded from model inputs: ${preview.ignored_columns.join(', ')}.`}
      </p>

      <details className="pw-details">
        <summary>Preview the first 10 rows</summary>
        <div className="table-scroll"><table>
          <thead><tr><th>Record</th>{FEATURES.map(name=><th key={name}>{name}</th>)}<th>Validation</th></tr></thead>
          <tbody>{preview.rows.slice(0,10).map(row=><tr key={row.row_number}>
            <td>{row.case_id || row.row_number}</td>
            {FEATURES.map(name=><td key={name}>{row.values[name]}</td>)}
            <td>{row.validation_errors.join('; ') || 'Ready'}</td>
          </tr>)}</tbody>
        </table></div>
      </details>

      <label className="csv-confirm">
        <input type="checkbox" checked={confirmed} disabled={busy}
          onChange={event=>setConfirmed(event.target.checked)} />
        I confirm these columns use the input units shown above.
      </label>

      <div className="csv-actions">
        <button className="button primary" disabled={busy || !confirmed}
          onClick={()=>void score()}>
          {results.length ? 'Run analysis again' : 'Analyze CSV'}
        </button>
        {busy && <button className="button secondary"
          onClick={()=>running.current?.abort()}>Stop</button>}
        <button className="button secondary" disabled={!results.length}
          onClick={exportResults}>↓ Download results</button>
      </div>

      <progress className="csv-progress" max={100} value={progress}
        aria-label="CSV rows processed" />
      <p className="pw-small">
        {results.length} of {preview.row_count} rows processed.
        Stopping retains completed batches; unprocessed rows are marked in the download.
      </p>

      {results.length>0 && <section className="directory-card">
        <div className="directory-toolbar">
          <div><h2>Analysis results</h2>
            <p>Flags combine model scoring and explicit data-quality rules.</p></div>
          <label>Show{' '}
            <select value={filter} onChange={event=>{setFilter(event.target.value);setPage(0);}}>
              <option value="all">All results</option>
              <option value="flagged">Flagged for review</option>
              <option value="unflagged">Not flagged</option>
              <option value="invalid">Invalid rows</option>
            </select>
          </label>
        </div>
        <div className="table-scroll"><table>
          <thead><tr><th>Record</th><th>Result</th><th>Score</th><th>Threshold</th><th>Details</th></tr></thead>
          <tbody>{visible.slice(page*20,page*20+20).map(row=><tr key={row.row_number}>
            <td>{sourceRows.get(row.row_number)?.case_id || `Row ${row.row_number}`}</td>
            <td><span className={`pw-badge ${row.status==='invalid'||row.result?.flagged_for_review?'pw-amber':''}`}>
              {row.status==='invalid'?'Invalid':row.result?.flagged_for_review?'Flagged for review':'Not flagged'}
            </span></td>
            <td>{row.result?.anomaly_score.toFixed(4) ?? '—'}</td>
            <td>{row.result?.threshold.toFixed(4) ?? '—'}</td>
            <td><button className="record-button" onClick={()=>setSelected(row)}>Inspect ↗</button></td>
          </tr>)}</tbody>
        </table></div>
        {visible.length===0 && <p className="state-box">No results match this filter.</p>}
        <footer className="pagination">
          <span>{visible.length} matching rows · Page {page+1}</span>
          <div>
            <button className="button secondary" disabled={page===0} onClick={()=>setPage(v=>v-1)}>← Previous</button>
            <button className="button secondary" disabled={(page+1)*20>=visible.length} onClick={()=>setPage(v=>v+1)}>Next →</button>
          </div>
        </footer>
      </section>}

      {selected && <article className="source-card">
        <div className="pw-row"><h3>Record {selected.row_number}</h3>
          <button className="button secondary" onClick={()=>setSelected(null)}>Close ×</button></div>
        {selected.errors?.map((message,index)=><p className="error-box" key={index}>{message}</p>)}
        {selected.result && <>
          <p><strong>ML flag:</strong> {selected.result.ml_flagged?'Yes':'No'}</p>
          <p><strong>Largest reconstruction discrepancy:</strong>{' '}
            {selected.result.largest_error_feature.replaceAll('_',' ')}</p>
          <p className="pw-small">This does not prove which input is incorrect.</p>
          {selected.result.data_quality_issues.map((message,index)=><p className="pw-notice" key={index}>{message}</p>)}
          <p className="pw-small">{selected.result.interpretation}</p>
        </>}
        <details className="pw-details"><summary>Input values and complete result</summary>
          <pre>{JSON.stringify({input:sourceRows.get(selected.row_number),output:selected},null,2)}</pre>
        </details>
      </article>}
    </>}

    {preview && originalFile && <SavePatientRecords
      key={`${originalFile.name}-${originalFile.lastModified}-${originalFile.size}`}
      file={originalFile}
      token={token}
      unitsConfirmed={confirmed}
      analysisBusy={busy}
      onUnauthorized={onUnauthorized}
    />}

    <p className="pw-notice">
      Analysis alone does not save records. Use “Save patient records” explicitly
      to store patient-linked panels. Analysis results are not saved as scoring
      history; download results before leaving this page.
      Synthetic-data model; flags are not diagnoses or confirmed data errors.
      An unflagged row is not proof of clinical normality.
    </p>
  </section>;
}
