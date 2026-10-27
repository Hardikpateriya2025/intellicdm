type Props = {
  reference: string;
  value: Record<string, unknown>;
};

function readableDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', timeZoneName: 'short',
  });
}

export default function SourceCard({ reference, value }: Props) {
  const record =
    value.record && typeof value.record === 'object' &&
    !Array.isArray(value.record)
      ? value.record as Record<string, unknown>
      : value;

  function text(key: string) {
    const field = record[key];
    return typeof field === 'string' || typeof field === 'number'
      ? String(field)
      : '';
  }

  const title = text('display_name') || text('test_name') ||
    text('reason') || 'Saved source record';

  const note = text('text') || text('note');
  const measuredValue = text('value');
  const unit = text('unit');

  const fields: [string, string][] = [
    ['collected_at', 'Collected'],
    ['visited_at', 'Encounter date'],
    ['created_at', 'Recorded'],
    ['status', 'Recorded status'],
    ['review_status', 'Review status'],
    ['reviewer_name', 'Reviewer'],
  ];

  return <article className="source-card">
    <header className="source-card-heading">
      <span className="source-reference">{reference}</span>
      <div>
        <p className="eyebrow">SUPPORTING RECORD</p>
        <h4>{title}</h4>
      </div>
    </header>

    {measuredValue !== '' && <div className="source-measurement">
      <strong>{measuredValue}</strong>
      <span>{unit || 'Unit not supplied'}</span>
    </div>}

    {note && <blockquote className="source-note">{note}</blockquote>}

    <dl className="source-fields">
      {fields.filter(([key]) => text(key) !== '').map(([key,label]) =>
        <div key={key}>
          <dt>{label}</dt>
          <dd>{['collected_at','visited_at','created_at'].includes(key)
            ? readableDate(text(key))
            : text(key).replaceAll('_', ' ')}</dd>
        </div>
      )}
    </dl>

    {record.reviewer_account_authenticated === true &&
      <p className="pw-small">Review attribution: authenticated account.</p>}

    {record.reviewer_account_authenticated === false &&
      <p className="pw-small">Review attribution: no authenticated account link.</p>}

    <details className="pw-details">
      <summary>Source identifiers and original record</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  </article>;
}
