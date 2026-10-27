import { useEffect, useRef, useState } from 'react';

type Props = {
  file: File | null;
  token: string;
  unitsConfirmed: boolean;
  analysisBusy: boolean;
  onUnauthorized: () => void;
};

type Validation = {
  panels: number;
  patient_identifiers: number;
  ignored_columns: string[];
  sample: {
    record: number;
    medical_record_number: string;
    patient_name: string;
    visited_at: string;
    collected_at: string;
  }[];
  notice: string;
};

type Saved = {
  status: string;
  processed_panels: number;
  created: {patients: number; encounters: number; lab_results: number};
  reused_panels: number;
  patient_ids: string[];
  encounter_ids: string[];
  notice: string;
};

const headers = [
  'medical_record_number','first_name','last_name','date_of_birth',
  'visited_at','collected_at','encounter_reason',
  'glucose','creatinine','urea_nitrogen','sodium',
  'potassium','chloride','calcium','total_co2',
];

function template() {
  const url = URL.createObjectURL(new Blob(
    [headers.join(',') + '\r\n'],
    {type:'text/csv;charset=utf-8'},
  ));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'patient-records-template.csv';
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export default function SavePatientRecords({
  file, token, unitsConfirmed, analysisBusy, onUnauthorized,
}: Props) {
  const [validation, setValidation] = useState<Validation|null>(null);
  const [saved, setSaved] = useState<Saved|null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [identityConfirmed, setIdentityConfirmed] = useState(false);
  const [role, setRole] = useState('');
  const lock = useRef(false);
  const current = useRef<File|null>(file);
  current.current = file;
  const unauthorized = useRef(onUnauthorized);
  unauthorized.current = onUnauthorized;

  useEffect(() => {
    setValidation(null);
    setSaved(null);
    setError('');
    setIdentityConfirmed(false);
  }, [file]);

  useEffect(() => {
    const controller = new AbortController();
    setRole('');
    fetch('/api/auth/me', {
      headers:{Authorization:`Bearer ${token}`},
      signal:controller.signal,
    }).then(async response => {
      if (response.status === 401) unauthorized.current();
      if (!response.ok) throw new Error('Could not verify your account permissions.');
      return response.json();
    }).then(user => {
      if (!controller.signal.aborted) setRole(user.role);
    }).catch(err => {
      if (!controller.signal.aborted) setError(String(err));
    });
    return () => controller.abort();
  }, [token]);

  async function send(save: boolean) {
    if (!file || lock.current || analysisBusy) return;
    if (save && (!validation || !identityConfirmed || !unitsConfirmed)) return;
    const chosen = file;
    lock.current = true;
    setBusy(true);
    setError('');
    try {
      const form = new FormData();
      form.append('file', chosen);
      if (save) form.append('units_confirmed', String(unitsConfirmed));
      const response = await fetch(
        `/api/csv/patient-records/${save ? 'save' : 'validate'}`,
        {
          method:'POST',
          headers:{Authorization:`Bearer ${token}`},
          body:form,
        },
      );
      const body = await response.json().catch(() => null);
      if (response.status === 401) unauthorized.current();
      if (!response.ok) {
        const detail = typeof body?.detail === 'string'
          ? body.detail : `Request failed (${response.status}).`;
        throw new Error(detail);
      }
      if (current.current !== chosen) return;
      if (save) setSaved(body);
      else {
        setValidation(body);
        setIdentityConfirmed(false);
      }
    } catch (err) {
      if (current.current === chosen) {
        setError(
          (err instanceof Error ? err.message : 'Request failed.') +
          (save ? ' If the connection failed after submission, retrying an identical file reuses matching panels.' : ''),
        );
      }
    } finally {
      lock.current = false;
      setBusy(false);
    }
  }

  const allowed = role === 'admin' || role === 'doctor';

  return <section className="directory-card" style={{padding:24,marginTop:24}}>
    <div className="pw-row">
      <div>
        <p className="eyebrow">PERSISTENT PATIENT RECORDS</p>
        <h2>Save patient records</h2>
      </div>
      <button className="button secondary" onClick={template}>
        ↓ Patient-record template
      </button>
    </div>
    <p className="pw-small">
      Add patient details, visits and lab results from your file.
      Each upload can save up to 200 lab panels.
      Patients are matched using their medical record number.
      Conflicting details must be resolved before saving.
    </p>
    <details className="pw-details">
      <summary>Required patient columns and date formats</summary>
      <p className="pw-small">
        Include medical_record_number, first_name, last_name, date_of_birth,
        visited_at, collected_at and encounter_reason, plus the eight chemistry columns.
        Birth date: YYYY-MM-DD. Visit and collection timestamps must include
        a timezone, for example 2026-10-20T10:15:00+05:30.
        Extra columns are not saved.
      </p>
      <p className="pw-small">
        A chemistry-only file needs real patient linkage before saving.
        Do not use a case number as a patient identity unless you have explicitly
        assigned that identifier in your dataset.
      </p>
    </details>

    {!allowed && <p className="pw-notice">
      {role ? 'Only admin and doctor accounts can save patient records.'
        : 'Checking account permissions…'}
    </p>}

    <button className="button secondary"
      disabled={!allowed || !file || busy || analysisBusy}
      onClick={() => void send(false)}>
      {busy ? 'Working…' : 'Check patient details'}
    </button>

    {error && <p className="error-box" role="alert">{error}</p>}

    {validation && <>
      <p className="pw-notice">
        {validation.panels} lab panels for {validation.patient_identifiers} patient identifiers.
        The required details are present. Please check the preview before saving.
        We will also check for conflicts with existing records when you save.
      </p>
      <div className="table-scroll"><table>
        <thead><tr><th>Row</th><th>Patient</th><th>Medical record number</th><th>Sample collected</th></tr></thead>
        <tbody>{validation.sample.map(row => <tr key={row.record}>
          <td>{row.record}</td><td>{row.patient_name}</td>
          <td>{row.medical_record_number}</td><td>{new Date(row.collected_at).toLocaleString(undefined, {
            dateStyle: 'medium',
            timeStyle: 'short',
          })}</td>
        </tr>)}</tbody>
      </table></div>
      <p className="pw-small">Showing the first five entries. Saving includes all entries in this file. Times are shown in your local timezone.</p>
      <label className="csv-confirm">
        <input type="checkbox" checked={identityConfirmed} disabled={busy}
          onChange={event => setIdentityConfirmed(event.target.checked)} />
        I checked the patient identities, visit details and collection times for this file.
      </label>
      {!unitsConfirmed && <p className="pw-small">
        Also confirm the measurement units in the CSV analysis section above.
      </p>}
      <button className="button primary"
        disabled={!allowed || busy || analysisBusy || !identityConfirmed || !unitsConfirmed}
        onClick={() => void send(true)}>
        {busy ? 'Working…' : 'Save patient records'}
      </button>
    </>}

    {saved && <div className="pw-notice" role="status">
      <strong>Patient records saved successfully.</strong>
      <p>
        New patient records: {saved.created.patients}<br />
        New visits: {saved.created.encounters}<br />
        New lab results: {saved.created.lab_results}
        {saved.reused_panels > 0 && <>
          <br />Already saved: {saved.reused_panels} matching lab panels.
          These were not added again.
        </>}
      </p>
      <p>
        Your patient details, visits and lab results are now available in
        Patient directory. Existing records have been preserved.
      </p>
      <p>
        To check a saved visit for unusual results, open the patient,
        select the visit and run the anomaly check.
      </p>
      <p>Find the patient in Patient directory using their name or medical record number.</p>

    </div>}
    <p className="pw-small">
      Keep this page open until saving finishes.
      Saving adds the records; it does not automatically run an anomaly check
      or send them for review.
    </p>
  </section>;
}
