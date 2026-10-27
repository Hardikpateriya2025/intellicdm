import { useEffect, useRef, useState } from 'react';

type Saved = {
  history_id: string;
  encounter_id: string;
  scored_at: string;
  snapshot: {
    collected_at?: string;
    input_measurements?: Record<string, number | string>;
    source_lab_result_ids?: Record<string, string[]>;
    newer_unusable_panel_count?: number;
    result?: {
      units?: Record<string, string>;
      interpretation?: string;
      known_limitations?: string[];
      largest_error_feature?: string;
    };
  };
};

type Props = {
  historyId: string;
  token: string;
  onUnauthorized: () => void;
};

const names: Record<string, string> = {
  glucose: 'Glucose',
  creatinine: 'Creatinine',
  urea_nitrogen: 'Urea nitrogen',
  sodium: 'Sodium',
  potassium: 'Potassium',
  chloride: 'Chloride',
  calcium: 'Calcium',
  total_co2: 'Total CO₂',
};

export default function SavedPanel({
  historyId, token, onUnauthorized,
}: Props) {
  const [data, setData] = useState<Saved | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [refresh, setRefresh] = useState(0);
  const unauthorized = useRef(onUnauthorized);
  unauthorized.current = onUnauthorized;

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError('');
    setBusy(true);

    async function load() {
      try {
        const response = await fetch(
          `/api/ml/anomaly-history/${historyId}/snapshot`,
          {
            headers: { Authorization: `Bearer ${token}` },
            signal: controller.signal,
          },
        );
        const body = await response.json().catch(() => null);

        if (controller.signal.aborted) return;

        if (response.status === 401) {
          unauthorized.current();
          return;
        }

        if (!response.ok) {
          throw new Error(
            typeof body?.detail === 'string'
              ? body.detail
              : `Saved panel could not be loaded (${response.status}).`,
          );
        }

        if (
          body?.history_id !== historyId ||
          !body?.snapshot ||
          typeof body.snapshot !== 'object' ||
          Array.isArray(body.snapshot)
        ) {
          throw new Error('The response did not match the selected scoring record.');
        }

        setData(body);
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(
            err instanceof Error ? err.message : 'Unable to load saved panel.',
          );
        }
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }

    void load();
    return () => controller.abort();
  }, [historyId, token, refresh]);

  const measurements = Object.entries(
    data?.snapshot.input_measurements || {},
  );
  const result = data?.snapshot.result;

  return <section className="source-card" aria-label="Saved scoring evidence">
    <header className="pw-row">
      <div>
        <p className="eyebrow">EVIDENCE AT SCORING TIME</p>
        <h3>Panel used for this score</h3>
      </div>
      <button className="button secondary" disabled={busy}
        onClick={() => setRefresh(value => value + 1)}>
        ↻ Reload evidence
      </button>
    </header>

    <p className="pw-small">
      These are the historical inputs saved with this scoring record.
      They are not a new measurement or a fresh model run.
    </p>

    {busy
      ? <p role="status" className="state-box">Loading saved evidence…</p>
      : error
        ? <p role="alert" className="error-box">{error}</p>
        : data && <>
          {measurements.length === 0
            ? <p className="state-box">
                No input measurements are included in this saved snapshot.
              </p>
            : <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Measurement</th>
                      <th>Saved value</th>
                      <th>Unit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {measurements.map(([name, value]) => <tr key={name}>
                      <td><strong>{names[name] || name.replaceAll('_', ' ')}</strong></td>
                      <td>{String(value)}</td>
                      <td>{result?.units?.[name] || 'Not recorded'}</td>
                    </tr>)}
                  </tbody>
                </table>
              </div>
          }

          {(data.snapshot.newer_unusable_panel_count || 0) > 0 &&
            <p className="pw-notice">
              {data.snapshot.newer_unusable_panel_count} newer unusable
              panel(s) were skipped when this score was generated.
            </p>}

          {result?.largest_error_feature && <p className="pw-small">
            Largest reconstruction discrepancy:{' '}
            <strong>
              {names[result.largest_error_feature] ||
                result.largest_error_feature.replaceAll('_', ' ')}
            </strong>.
            This does not establish which measurement, if any, is incorrect.
          </p>}

          {result?.interpretation &&
            <p className="pw-notice">{result.interpretation}</p>}

          {result?.known_limitations && result.known_limitations.length > 0 &&
            <details className="pw-details">
              <summary>Model limitations</summary>
              <ul>
                {result.known_limitations.map((item, index) =>
                  <li key={index}>{item}</li>)}
              </ul>
            </details>}

          <details className="pw-details">
            <summary>Technical details — original saved evidence</summary>
            <pre>{JSON.stringify(data.snapshot, null, 2)}</pre>
          </details>
        </>
    }
  </section>;
}
