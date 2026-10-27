import { useEffect, useRef, useState } from 'react';
import RecordForm from './RecordForm';

type Account = {
  id: string;
  username: string;
  display_name: string;
  role: string;
  is_active: boolean;
};

type Page = {
  items: Account[];
  has_more: boolean;
  limit: number;
  offset: number;
};

type Props = {
  token: string;
  onUnauthorized: () => void;
};

export default function Users({ token, onUnauthorized }: Props) {
  const [data, setData] = useState<Page | null>(null);
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');

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
          `/api/admin/users?limit=20&offset=${offset}`,
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
              : `Accounts could not be loaded (${response.status}).`,
          );
        }
        if (!Array.isArray(body?.items)) {
          throw new Error('Unexpected account-list response.');
        }

        setData(body);
      } catch (err) {
        if (!controller.signal.aborted) {
          setError(
            err instanceof Error ? err.message : 'Unable to load accounts.',
          );
        }
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }

    void load();
    return () => controller.abort();
  }, [token, offset, refresh]);

  return <section className="team-page">
    <header className="page-heading">
      <div>
        <p className="eyebrow">WORKSPACE ADMINISTRATION</p>
        <h1>Your team<span>.</span></h1>
        <p className="muted">
          Give each collaborator an account and a defined workspace role.
        </p>
      </div>
      <button className="button secondary" disabled={busy}
        onClick={() => setRefresh(value => value + 1)}>
        ↻ Refresh accounts
      </button>
    </header>

    <div className="team-roles">
      <article>
        <span className="team-role-icon" aria-hidden="true">▦</span>
        <h3>Doctor</h3>
        <p>Add patient records, encounters and lab measurements.
          Explore records and use analysis tools.</p>
      </article>
      <article>
        <span className="team-role-icon" aria-hidden="true">◇</span>
        <h3>Reviewer</h3>
        <p>Read records, use analysis tools and submit reviews
          linked to an authenticated account.</p>
      </article>
      <article>
        <span className="team-role-icon" aria-hidden="true">⌘</span>
        <h3>Administrator</h3>
        <p>Manage accounts, add clinical records and submit reviews.
          New administrator accounts cannot be created here.</p>
      </article>
    </div>

    <RecordForm
      title="Create account"
      path="/admin/users"
      token={token}
      onUnauthorized={onUnauthorized}
      onSaved={() => {
        setOffset(0);
        setRefresh(value => value + 1);
      }}
      description="Create a doctor or reviewer account. Usernames must start with a lowercase letter or number and contain only lowercase letters, numbers, dots, underscores or hyphens. Passwords require 12–128 characters."
      fields={[
        {name:'username',label:'Username',min:3,max:100},
        {name:'display_name',label:'Display name',max:100},
        {name:'password',label:'Password',type:'password',min:12,max:128},
        {
          name:'role',
          label:'Workspace role',
          options:[['reviewer','Reviewer'],['doctor','Doctor']],
        },
      ]}
    />

    <section className="directory-card" aria-label="Workspace accounts">
      <div className="directory-toolbar">
        <div>
          <h2>Workspace accounts</h2>
          <p>Account access and assigned roles</p>
        </div>
        <span className="pill">ADMIN ACCESS</span>
      </div>

      {busy
        ? <p className="state-box" role="status">Loading accounts…</p>
        : error
          ? <p className="error-box state-box" role="alert">{error}</p>
          : !data?.items.length
            ? <p className="state-box">No accounts on this page.</p>
            : <div className="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>Account</th>
                      <th>Username</th>
                      <th>Role</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.items.map(account => <tr key={account.id}>
                      <td>
                        <div className="patient-cell">
                          <span className="avatar">
                            {account.display_name.slice(0,1).toUpperCase()}
                          </span>
                          <div>
                            <strong>{account.display_name}</strong>
                            <small>Workspace account</small>
                          </div>
                        </div>
                      </td>
                      <td>{account.username}</td>
                      <td><span className="pw-badge">{account.role}</span></td>
                      <td>
                        <span className={
                          `pw-badge ${account.is_active ? '' : 'pw-amber'}`
                        }>
                          {account.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                    </tr>)}
                  </tbody>
                </table>
              </div>
      }

      <footer className="pagination">
        <span>Page {offset / 20 + 1}</span>
        <div>
          <button className="button secondary"
            disabled={busy || offset === 0}
            onClick={() => setOffset(value => value - 20)}>
            ← Previous
          </button>
          <button className="button secondary"
            disabled={busy || !data?.has_more}
            onClick={() => setOffset(value => value + 20)}>
            Next →
          </button>
        </div>
      </footer>
    </section>

    <p className="pw-notice">
      This prototype uses workspace-wide role access.
      An authenticated account does not establish professional qualifications
      or independently verify a person's identity.
    </p>
  </section>;
}
