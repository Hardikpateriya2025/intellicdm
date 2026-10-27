import { useEffect, useId, useRef, useState } from 'react';
import type { FormEvent } from 'react';

type Field = {
  name: string;
  label: string;
  type?: string;
  max?: number;
  min?: number;
  optional?: boolean;
  options?: [string, string][];
};

type Props = {
  title: string;
  description?: string;
  fields: Field[];
  path: string;
  token: string;
  onUnauthorized: () => void;
  onSaved: () => void;
  transform?: (values: Record<string, string>) => unknown;
};

export default function RecordForm({
  title, description, fields, path, token,
  onUnauthorized, onSaved, transform,
}: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const lock = useRef(false);
  const mounted = useRef(true);
  const id = useId();

  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (lock.current) return;

    const form = event.currentTarget;
    const values = Object.fromEntries(
      Array.from(new FormData(form).entries()).map(
        ([key, value]) => [key, String(value)],
      ),
    );

    lock.current = true;
    setBusy(true); setError(''); setSaved(false);

    try {
      const payload = transform ? transform(values) : values;
      const response = await fetch(`/api${path}`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => null);

      if (response.status === 401) {
        onUnauthorized();
        return;
      }
      if (!response.ok) {
        const detail = data?.detail;
        const message = typeof detail === 'string' ? detail
          : Array.isArray(detail)
            ? detail.map((item: {loc?: string[]; msg?: string}) =>
                `${item.loc?.slice(1).join('.') || 'Input'}: ${item.msg || 'Invalid value'}`
              ).join('; ')
            : `Unable to save (${response.status}).`;
        throw new Error(message);
      }

      if (mounted.current) {
        form.reset();
        setOpen(false);
        setSaved(true);
        onSaved();
      }
    } catch (err) {
      if (mounted.current) {
        setError(
          (err instanceof Error ? err.message : 'Unable to save.') +
          ' If the connection was interrupted, inspect saved records before retrying.',
        );
      }
    } finally {
      lock.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return <div className="entry-box">
    <button className="button secondary" disabled={busy}
      aria-expanded={open} aria-controls={id}
      onClick={() => {setOpen(!open); setSaved(false);}}>
      {open ? `Close ${title.toLowerCase()} form` : `+ ${title}`}
    </button>

    {saved && <p role="status" className="pw-notice">
      Record saved successfully.
    </p>}

    {open && <form id={id} className="entry-form" onSubmit={submit}>
      <h3>{title}</h3>
      <p className="pw-small">
        {description || 'Create a new saved record. Required fields are marked with *.'}
      </p>

      <fieldset disabled={busy}>
        <div className="entry-grid">
          {fields.map(field => <label key={field.name}>
            <span>{field.label}{!field.optional && ' *'}</span>
            {field.options
              ? <select name={field.name} required={!field.optional}>
                  {field.options.map(([value,label]) =>
                    <option key={value} value={value}>{label}</option>)}
                </select>
              : field.type === 'textarea'
                ? <textarea name={field.name}
                    required={!field.optional} maxLength={field.max} />
                : <input name={field.name}
                    type={field.type || 'text'}
                    required={!field.optional}
                    minLength={field.min} maxLength={field.max}
                    step={field.type === 'number' ? 'any' : undefined}
                    autoComplete={field.type === 'password' ? 'new-password' : 'off'}
                  />}
          </label>)}
        </div>
      </fieldset>

      {error && <p role="alert" className="error-box">{error}</p>}
      <button className="button primary" disabled={busy}>
        {busy ? 'Saving…' : 'Save record'}
      </button>
    </form>}
  </div>;
}
