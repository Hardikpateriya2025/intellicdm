import CsvTesting from './CsvTesting';
import Users from './Users';
import RecordForm from './RecordForm';
import Dashboard from './Dashboard';
import ReviewQueue from './ReviewQueue';
import PatientWorkspace from './PatientWorkspace';
import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';

type User = {
  id: string;
  username: string;
  display_name: string;
  role: string;
};

type Patient = {
  id: string;
  medical_record_number: string;
  first_name: string;
  last_name: string;
  date_of_birth: string;
};

class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  path: string,
  token: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (token) headers.set('Authorization', `Bearer ${token}`);
  const response = await fetch(`/api${path}`, { ...options, headers });
  const data = await response.json().catch(() => null);

  if (!response.ok) {
    const detail = data?.detail;
    const message = typeof detail === 'string'
      ? detail
      : response.status === 401
        ? 'Please sign in again.'
        : response.status === 403
          ? 'Your account does not have access to this action.'
          : `The request could not be completed (${response.status}).`;
    throw new ApiError(response.status, message);
  }
  return data as T;
}

function Brand() {
  return <div className="brand">
    <span className="brand-symbol" aria-hidden="true">✳</span>
    <span>Intelli<span className="brand-light">CDM</span><small>CLINICAL INTELLIGENCE</small></span>
  </div>;
}

function Login({ onLogin, notice }: {
  onLogin: (token: string, user: User) => void;
  notice: string;
}) {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const result = await request<{ access_token: string }>('/auth/token', '', {
        method: 'POST',
        body: new URLSearchParams({ username: username.trim(), password }),
      });
      const user = await request<User>('/auth/me', result.access_token);
      onLogin(result.access_token, user);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to sign in.');
    } finally {
      setBusy(false);
    }
  }

  return <main className="login-layout">
    <section className="login-story">
      <Brand />
      <div className="story-copy">
        <span className="pill dark-pill"><i /> YOUR CLINICAL WORKSPACE</span>
        <h1>A clearer view.<br />A smarter<br /><em>starting point.</em></h1>
        <p>Bring patient records, intelligent discovery and thoughtful review into one connected workspace.</p>
      </div>
      <div className="orbit-art" aria-hidden="true">
        <div className="orbit orbit-one" /><div className="orbit orbit-two" />
        <div className="orbit-core">✳</div>
        <div className="float-card float-one"><span>01</span><div>Connected records<small>Context, in one place</small></div></div>
        <div className="float-card float-two"><span>02</span><div>AI-assisted discovery<small>Answers with sources</small></div></div>
        <div className="float-card float-three"><span>03</span><div>Human-led review<small>Keep decisions accountable</small></div></div>
      </div>
      <footer className="story-footer"><span>Designed for clarity.</span><span>Built for exploration. ↗</span></footer>
    </section>

    <section className="login-panel">
      <div className="login-top"><span className="pill">SYNTHETIC DATA DEMO</span><span>IntelliCDM / Workspace</span></div>
      <div className="login-form-wrap">
        <div className="welcome-icon" aria-hidden="true">↗</div>
        <p className="eyebrow">WELCOME BACK</p>
        <h2>Your workspace<br />awaits.</h2>
        <p className="muted login-description">Sign in to explore records and continue your work.</p>
        <form onSubmit={submit}>
          <label htmlFor="username">Username</label>
          <input id="username" autoComplete="username" required
            placeholder="Enter your username" value={username}
            onChange={e => setUsername(e.target.value)} disabled={busy} />
          <div className="password-label"><label htmlFor="password">Password</label><span>Use your assigned account</span></div>
          <div className="password-input">
            <input id="password" type={visible ? 'text' : 'password'}
              autoComplete="current-password" required placeholder="Enter your password"
              value={password} onChange={e => setPassword(e.target.value)} disabled={busy} />
            <button type="button" className="show-password" aria-pressed={visible}
              onClick={() => setVisible(!visible)}>{visible ? 'Hide' : 'Show'}</button>
          </div>
          {(error || notice) && <p role="alert" className="error-box">{error || notice}</p>}
          <button className="button primary login-submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Enter workspace'} <span aria-hidden="true">↗</span>
          </button>
        </form>
        <p className="account-help">Need an account? Contact your workspace administrator.</p>
        <div className="login-disclaimer"><span aria-hidden="true">◇</span><p>A development workspace using synthetic records.<br />AI outputs support review and are not diagnoses.</p></div>
      </div>
      <footer className="login-footer"><span>IntelliCDM</span><span>Clinical Data Management & Intelligence</span></footer>
    </section>
  </main>;
}

const PAGE_SIZE = 20;

function Workspace({ token, user, logout }: {
  token: string;
  user: User;
  logout: (message?: string) => void;
}) {
  const [page, setPage] = useState('dashboard');

  function navigate(next: string) {
    setSelected(null);
    setPage(next);
    window.scrollTo({ top: 0 });
  }

  const [patients, setPatients] = useState<Patient[]>([]);
  const [draft, setDraft] = useState('');
  const [query, setQuery] = useState('');
  const [offset, setOffset] = useState(0);
  const [more, setMore] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [selected, setSelected] = useState<Patient | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError('');
    setPatients([]);
    setMore(false);
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE + 1), offset: String(offset),
    });
    if (query) params.set('q', query);

    request<Patient[]>(`/patients?${params}`, token, { signal: controller.signal })
      .then(data => {
        if (controller.signal.aborted) return;
        setPatients(data.slice(0, PAGE_SIZE));
        setMore(data.length > PAGE_SIZE);
      })
      .catch(err => {
        if (controller.signal.aborted) return;
        if (err instanceof ApiError && err.status === 401) {
          logout('Your session expired. Please sign in again.');
        } else {
          setError(err instanceof Error ? err.message : 'Unable to load patients.');
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
    // Logout performs an app-level session reset.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, query, offset, refresh]);

  useEffect(() => {
    if (!selected) return;
    function close(event: KeyboardEvent) {
      if (event.key === 'Escape') setSelected(null);
    }
    window.addEventListener('keydown', close);
    return () => window.removeEventListener('keydown', close);
  }, [selected]);

  return <div className="workspace">
    <aside className="sidebar">
      <Brand />
      <div className="workspace-label"><span className="workspace-square">S</span><div>Synthetic workspace<small>Development environment</small></div></div>
      <p className="nav-label">WORKSPACE</p>
      <nav aria-label="Main navigation">

        {[
          ['dashboard', '◈', 'Overview'],
          ['patients', '▦', 'Patient directory'],
          ['reviews', '◇', 'Review queue'],
          ['csv', '⇧', 'CSV analysis'],
          ...(user.role === 'admin'
            ? [['users', '⌘', 'Team & access']]
            : []),
        ].map(([key, icon, text]) => (
          <button
            key={key}
            className={`nav-item ${page === key ? 'active' : ''}`}
            aria-current={page === key ? 'page' : undefined}
            onClick={() => navigate(key)}
          >
            <span aria-hidden="true">{icon}</span>
            {text}
            <span className="nav-arrow">↗</span>
          </button>
        ))}

      </nav>
      <div className="sidebar-bottom">
        <div className="sidebar-note"><span>✧</span><h3>Intelligence with context.</h3><p>Explore saved records. Keep sources close and human review at the centre.</p></div>
        <div className="profile"><span className="avatar">{user.display_name.slice(0, 1).toUpperCase()}</span><div><strong>{user.display_name}</strong><small>{user.role}</small></div></div>
        <button className="logout" onClick={() => logout()}>Sign out <span>↗</span></button>
      </div>
    </aside>

    <div className="workspace-body">
      <header className="workspace-topbar">
        <span>Workspace <span className="breadcrumb-divider">/</span> <strong>{
          page === 'dashboard' ? 'Overview'
            : page === 'csv' ? 'CSV analysis'
            : page === 'users' ? 'Team & access'
            : page === 'reviews' ? 'Review queue'
            : 'Patients'
        }</strong></span>
        <span className="pill"><i /> SYNTHETIC DATA</span>
      </header>
      <main className="workspace-content" id="patients">
        {page === 'csv' && <CsvTesting
          token={token}
          onUnauthorized={() => logout('Your session expired. Please sign in again.')}
        />}
        {page === 'users' && user.role === 'admin' && (
          <Users
            token={token}
            onUnauthorized={() => logout('Your session expired. Please sign in again.')}
          />
        )}
        {page === 'dashboard' && (
          <Dashboard
            token={token}
            name={user.display_name}
            navigate={navigate}
            onUnauthorized={() => logout('Your session expired. Please sign in again.')}
          />
        )}
        {page === 'patients' && !selected && <>
        <section className="page-heading">
          <div><p className="eyebrow">CONNECTED RECORDS. CLEARER CONTEXT.</p><h1>Patient directory<span>.</span></h1><p className="muted">Every record is a starting point. Find the one you need.</p></div>
          <button className="button secondary" disabled={loading} onClick={() => setRefresh(v => v + 1)}>↻ Refresh records</button>
        </section>
        <section className="workspace-banner">
          <div><span className="pill dark-pill">YOUR RECORDS, CONNECTED</span><h2>Less searching.<br /><em>More understanding.</em></h2><p>Search saved patients by name or medical record number.</p></div>
          <div className="banner-art" aria-hidden="true"><span>✳</span><div className="banner-ring" /></div>
        </section>

        {['admin', 'doctor'].includes(user.role) && <RecordForm
          title="Register patient"
          path="/patients"
          token={token}
          onUnauthorized={() => logout('Please sign in again.')}
          onSaved={() => {
            setOffset(0); setDraft(''); setQuery('');
            setRefresh(value => value + 1);
          }}
          fields={[
            {name:'medical_record_number',label:'Medical record number',max:50},
            {name:'first_name',label:'First name',max:100},
            {name:'last_name',label:'Last name',max:100},
            {name:'date_of_birth',label:'Date of birth',type:'date'},
          ]}
        />}
        <section className="directory-card" aria-label="Patient directory">
          <div className="directory-toolbar">
            <div><h2>All patients</h2><p>{query ? `Results for “${query}”` : 'Browse your saved patient records'}</p></div>
            <form className="search-form" onSubmit={e => {
              e.preventDefault(); setQuery(draft.trim()); setOffset(0); setRefresh(v => v + 1);
            }}>
              <label className="sr-only" htmlFor="search">Search patient names or medical record numbers</label>
              <input id="search" type="search" placeholder="Search name or MRN…" maxLength={100}
                value={draft} onChange={e => setDraft(e.target.value)} />
              <button className="button primary" disabled={loading}>Search</button>
              {(query || draft) && <button type="button" className="button secondary"
                onClick={() => { setDraft(''); setQuery(''); setOffset(0); }}>Clear</button>}
            </form>
          </div>

          {error ? <div className="state-box error-box" role="alert">{error}<p>Check your backend connection and try Refresh records.</p></div>
            : loading ? <div className="state-box" role="status"><span className="spinner" />Loading patient records…</div>
            : patients.length === 0 ? <div className="state-box"><h3>No matching records</h3><p>Try another name or medical record number.</p></div>
            : <div className="table-scroll"><table>
              <thead><tr><th>Patient</th><th>Medical record number</th><th>Date of birth</th><th><span className="sr-only">Actions</span></th></tr></thead>
              <tbody>{patients.map((p, index) => <tr key={p.id}>
                <td><div className="patient-cell"><span className={`avatar tone-${index % 3}`}>{p.first_name.slice(0, 1)}{p.last_name.slice(0, 1)}</span><div><strong>{p.first_name} {p.last_name}</strong><small>Medical record number: {p.medical_record_number}</small></div></div></td>
                <td><span className="mrn">{p.medical_record_number}</span></td>
                <td>{p.date_of_birth}</td>
                <td><button className="record-button" onClick={() => setSelected(p)}
                  aria-label={`View ${p.first_name} ${p.last_name}`}>View record <span>↗</span></button></td>
              </tr>)}</tbody>
            </table></div>}
          <footer className="pagination">
            <span aria-live="polite">{loading ? 'Loading…' : `${patients.length} records on this page`} · Page {offset / PAGE_SIZE + 1}</span>
            <div><button className="button secondary" disabled={loading || offset === 0}
              onClick={() => setOffset(v => Math.max(0, v - PAGE_SIZE))}>← Previous</button>
              <button className="button secondary" disabled={loading || !!error || !more}
                onClick={() => setOffset(v => v + PAGE_SIZE)}>Next →</button></div>
          </footer>
        </section>
        </>}
        {page === 'reviews' && <ReviewQueue
          token={token}
          role={user.role}
          displayName={user.display_name}
          onUnauthorized={() => logout('Your session expired. Please sign in again.')}
        />
        }
        <footer className="workspace-footer"><span>IntelliCDM · Clinical intelligence workspace</span><span>Synthetic records · Development use</span></footer>

        {selected && <PatientWorkspace
          key={selected.id}
          patient={selected}
          role={user.role}
          token={token}
          onClose={() => setSelected(null)}
          onUnauthorized={() => logout('Your session expired. Please sign in again.')}
        />}
      </main>
    </div>
  </div>;
}

export default function App() {
  const [session, setSession] = useState<{ token: string; user: User } | null>(null);
  const [notice, setNotice] = useState('');

  useEffect(() => { document.title = 'IntelliCDM | Clinical Intelligence'; }, []);

  function logout(message = '') {
    setSession(null);
    setNotice(message);
  }

  return session
    ? <Workspace token={session.token} user={session.user} logout={logout} />
    : <Login notice={notice} onLogin={(token, user) => {
        setNotice(''); setSession({ token, user });
      }} />;
}
