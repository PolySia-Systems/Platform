import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Modal, useDirection } from '@mantine/core';
import type { Action, ActionCatalog, Component, Detail, Money, Page, Preview, Receipt, Receipts, Session, Snapshot } from './contract.generated';
import { ApiError, post, read } from './client';
import { m } from './messages';
import s from './Console.module.css';
import { EvidenceWorkspace, valueDirection } from './Workspaces';

type Intent = { preview_id: string; expected_revision: number; idempotency_key: string; context: string; identity: string };
type Tab = 'Overview' | 'Investigate' | 'Operate' | 'Evaluate' | 'System / Setup';
const names = { publication: m.source, financial: m.financial, supervision: m.supervision, worker: m.worker, publisher: m.publisher };
const stamp = (value: string | null | undefined, locale = 'en-GB') => value
  ? new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'medium', timeZone: 'UTC' }).format(new Date(value)) + ' UTC' : m.unknown;
const identifier = (value: string | null | undefined) => <bdi title={value ?? m.unknown} className={s.identifier} dir="ltr">{value ?? m.unknown}</bdi>;
function Amount({ value }: { value: Money | null | undefined }) {
  return <span className={s.amount} title={value?.meaning}><bdi dir="ltr">{value?.value ?? m.unknown}</bdi>
    <span className={s.unit}>{value?.unit ?? m.unknown}</span></span>;
}
function Timestamp({ value, locale }: { value: string | null | undefined; locale?: string }) {
  return <bdi dir="ltr">{stamp(value, locale)}</bdi>;
}
function Badge({ children, alert = false }: { children: React.ReactNode; alert?: boolean }) {
  const uncertain = typeof children === 'string' && ['UNKNOWN', 'DENIED', 'EXPIRED', 'NOT_STARTED', 'PARTIAL', 'STALE', 'BLOCKED', 'FAILED', 'CLAIMED', 'REQUESTED', 'STOP', 'DRAIN', 'UNAVAILABLE', 'INCOMPATIBLE'].some(value => children.startsWith(value));
  return <span className={`${s.badge} ${alert || uncertain ? s.bad : ''}`}>{children}</span>;
}
function errorText(error: unknown): string {
  if (error instanceof ApiError) return error.status === 403 ? m.auth : error.status === 410 ? m.cursor : error.status === 409 ? m.conflict : m.missing;
  return error instanceof Error && error.message === 'incompatible_contract' ? m.contract : m.missing;
}
export default function App() {
  const example = new URLSearchParams(location.search).get('example') === '1';
  const { setDirection } = useDirection();
  const [tab, setTab] = useState<Tab>('Overview');
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [failure, setFailure] = useState('');
  const [authFailure, setAuthFailure] = useState('');
  const [clockSkew, setClockSkew] = useState(false);
  const [clock, setClock] = useState(Date.now());
  const anchor = useRef({ server: Date.now(), mono: performance.now() });
  const [history, setHistory] = useState<Receipts | null>(null);
  const [protective, setProtective] = useState<ActionCatalog | null>(null);
  const [historyError, setHistoryError] = useState('');
  const [historyCursor, setHistoryCursor] = useState('');
  const [refreshBusy, setRefreshBusy] = useState(false);
  const [workspaceRefresh, setWorkspaceRefresh] = useState(0);
  const refreshTask = useRef<Promise<void> | null>(null);
  const authEpoch = useRef(0);
  const [chosen, setChosen] = useState('');
  const [arguments_, setArguments] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<Preview | null>(null);
  const [intent, setIntent] = useState<Intent | null>(null);
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [commandState, setCommandState] = useState<'idle' | 'previewing' | 'preview' | 'sending' | 'uncertain' | 'absent' | 'recorded'>('idle');
  const [commandError, setCommandError] = useState('');
  const [lookupKey, setLookupKey] = useState('');
  const [inspectedReceipt, setInspectedReceipt] = useState<Receipt | null>(null);
  const [lookupError, setLookupError] = useState('');
  const activeIntent = useRef<Intent | null>(null);
  const recoverySequence = useRef(0);
  const historySequence = useRef(0);
  const recoveryRequest = useRef<AbortController | null>(null);
  const historyRequest = useRef<AbortController | null>(null);
  const epoch = useRef(0);
  const active = useRef(true);
  const currentIdentity = useRef('');
  const currentContext = useRef('');
  const selectedAction = useRef<Action | null>(null);
  const [rtl, setRtl] = useState(new URLSearchParams(location.search).get('locale') === 'fa-IR');
  const validIdentity = session !== null && !authFailure && clock < Date.parse(session.valid_until);
  const now = () => anchor.current.server + performance.now() - anchor.current.mono;
  const rememberIntent = (value: Intent | null) => { activeIntent.current = value; setIntent(value); };

  const invalidate = useCallback(() => {
    epoch.current += 1; setPreview(null);
    recoverySequence.current += 1; recoveryRequest.current?.abort();
    historySequence.current += 1; historyRequest.current?.abort();
    setInspectedReceipt(null); setLookupError('');
    // An ambiguous request identity stays visible for exact recovery, never replayed.
    setCommandState(previous => previous === 'sending' ? 'uncertain'
      : previous === 'uncertain' || previous === 'absent' ? previous : 'idle');
  }, []);
  const identityFailure = useCallback(() => {
    authEpoch.current += 1;
    currentIdentity.current = ''; setSession(null); setAuthFailure(m.auth);
    setSnapshot(null); setHistory(null); setReceipt(null); setProtective(null); invalidate();
  }, [invalidate]);

  const refresh = useCallback((): Promise<void> => {
    if (refreshTask.current) return refreshTask.current;
    const authentication = authEpoch.current;
    const current = () => active.current && authEpoch.current === authentication;
    setRefreshBusy(true);
    // Separate deadlines and settlement: history cannot exhaust snapshot/session budget.
    const task = Promise.allSettled([
      read<Session>('/session', 'Session').then(value => {
        if (!current()) return;
        if (value.bundle !== document.querySelector<HTMLMetaElement>('meta[name="bundle-source"]')?.content) throw Error('incompatible_contract');
        if (currentIdentity.current && currentIdentity.current !== value.identity) invalidate();
        currentIdentity.current = value.identity;
        anchor.current = { server: Date.parse(value.server_time), mono: performance.now() };
        setClockSkew(Math.abs(Date.now() - anchor.current.server) > 60_000);
        setSession(value); setAuthFailure(''); setClock(now());
      }).catch(error => { if (current()) { setAuthFailure(errorText(error)); invalidate();
        if (error instanceof ApiError && error.status === 403) identityFailure(); } }),
      read<Snapshot>('/snapshot', 'Snapshot').then(value => {
        if (!current()) return;
        const context = JSON.stringify([value.context, value.actions]);
        if (currentContext.current && currentContext.current !== context && !selectedAction.current?.protective) invalidate();
        currentContext.current = context; setSnapshot(value); setFailure('');
      }).catch(error => { if (current()) { setFailure(errorText(error));
        if (error instanceof ApiError && error.status === 403) identityFailure(); } }),
      read<Receipts>('/receipts', 'Receipts').then(value => {
        if (current()) { setHistory(value); setHistoryCursor(''); setHistoryError(''); }
      }).catch(error => { if (current()) { setHistoryError(m.historyUnavailable);
        if (error instanceof ApiError && error.status === 403) identityFailure(); } }),
      read<ActionCatalog>('/protective-actions', 'ActionCatalog').then(value => {
        if (current()) {
          const selected = selectedAction.current;
          if (selected?.protective && !value.actions.some(a => a.context === selected.context
            && a.operation === selected.operation && a.target === selected.target)) invalidate();
          setProtective(value);
        }
      }).catch(error => { if (current()) { setProtective(null);
        if (error instanceof ApiError && error.status === 403) identityFailure(); } }),
    ]).then(() => undefined).finally(() => { refreshTask.current = null; if (active.current) setRefreshBusy(false); });
    refreshTask.current = task;
    return task;
  }, [identityFailure, invalidate]);
  useEffect(() => {
    active.current = true;
    let running = false;
    const poll = async () => { if (running || document.hidden) return; running = true;
      try { await refresh(); } finally { running = false; } };
    void poll();
    const interval = setInterval(() => void poll(), 15_000);
    const tick = setInterval(() => { if (!document.hidden) setClock(now()); }, 1000);
    const visibility = () => { invalidate(); setClock(now()); if (!document.hidden) void poll(); };
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pageshow', visibility);
    return () => { active.current = false; clearInterval(interval); clearInterval(tick);
      recoveryRequest.current?.abort(); historyRequest.current?.abort();
      document.removeEventListener('visibilitychange', visibility); window.removeEventListener('pageshow', visibility); };
  }, [invalidate, refresh]);
  useEffect(() => { if (session && !validIdentity) invalidate(); }, [validIdentity, session, invalidate]);
  useEffect(() => { if (preview && clock >= Date.parse(preview.expires_at)) invalidate(); }, [clock, preview, invalidate]);
  useEffect(() => { setDirection(rtl ? 'rtl' : 'ltr'); document.documentElement.lang = rtl ? 'fa-IR' : 'en'; }, [rtl, setDirection]);

  const actions = [...(protective?.actions ?? []), ...(snapshot?.actions ?? []).filter(a => !a.protective)];
  const action = actions.find(a => a.operation + '|' + a.target === chosen);
  const argumentsReady = (action?.arguments ?? []).every(field => field.kind !== 'choice'
    || field.choices.some(choice => choice.value === arguments_[field.name]))
    && ((!arguments_.start && !arguments_.end) || (!!arguments_.start && !!arguments_.end
      && Date.parse(arguments_.start) < Date.parse(arguments_.end)));
  const changeAction = (value: string) => { if (['sending', 'uncertain', 'absent'].includes(commandState)) return;
    invalidate(); selectedAction.current = actions.find(a => a.operation + '|' + a.target === value) ?? null;
    setChosen(value); setArguments({}); rememberIntent(null); setReceipt(null); setCommandError(''); };
  const makePreview = async () => {
    if (!action || !validIdentity || !session) return;
    selectedAction.current = action;
    const version = ++epoch.current;
    setCommandState('previewing'); setCommandError('');
    try {
      const value = await post<Preview>('/preview', 'Preview', { operation: action.operation,
        target: action.target, context: action.context, identity: session.identity, arguments: arguments_ }, session.csrf);
      if (version !== epoch.current || value.identity !== currentIdentity.current || Date.parse(value.expires_at) <= now()) return;
      setPreview(value); rememberIntent({ preview_id: value.preview_id, expected_revision: value.expected_revision,
        idempotency_key: crypto.randomUUID(), context: value.context, identity: value.identity });
      setCommandState('preview');
    } catch (error) { if (version === epoch.current) { setCommandError(errorText(error)); setCommandState('idle');
      if (error instanceof ApiError && error.status === 403) identityFailure(); } }
  };
  const apply = async () => {
    if (!intent || !session || !preview || !validIdentity || Date.parse(preview.expires_at) <= now()) return;
    setCommandState('sending'); setCommandError('');
    const version = epoch.current;
    try {
      const value = await post<Receipt>('/apply', 'Receipt', intent, session.csrf);
      if (version !== epoch.current) return;
      setReceipt(value); setCommandState('recorded'); setPreview(null); void refresh();
    } catch (error) {
      if (version !== epoch.current) return;
      setCommandState('uncertain'); setCommandError(m.uncertain);
      if (error instanceof ApiError && error.status === 403) identityFailure();
    }
  };
  const recover = async (key: string) => {
    const captured = activeIntent.current;
    if (!key || !validIdentity || !session || captured?.idempotency_key !== key) return;
    const version = ++recoverySequence.current;
    recoveryRequest.current?.abort();
    const controller = new AbortController(); recoveryRequest.current = controller;
    const authentication = authEpoch.current, identity = currentIdentity.current, context = epoch.current;
    // Receipt reads use current authorization, not the original preview's expired identity.
    const current = () => active.current && version === recoverySequence.current
      && authentication === authEpoch.current && identity === currentIdentity.current
      && context === epoch.current && activeIntent.current === captured
      && now() < Date.parse(session.valid_until);
    try {
      const value = await read<Receipts>('/receipts?key=' + encodeURIComponent(key), 'Receipts',
        AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]));
      if (!current()) return;
      const found = value.items.find(row => row.idempotency_key === key);
      if (!found && value.items.length) throw Error('incompatible_contract');
      if (found) { setReceipt(found); setPreview(null); setCommandState(found.effect === 'UNKNOWN' ? 'uncertain' : 'recorded'); setCommandError(found.effect === 'UNKNOWN' ? m.unresolved : ''); }
      else { setCommandState('absent'); setCommandError(m.notFound); }
    } catch (error) { if (current() && !controller.signal.aborted) { setCommandError(errorText(error));
      if (error instanceof ApiError && error.status === 403) identityFailure(); } }
  };
  const inspectReceipt = async (key: string) => {
    if (!key || !validIdentity || !session) return;
    const version = ++historySequence.current;
    historyRequest.current?.abort();
    const controller = new AbortController(); historyRequest.current = controller;
    const authentication = authEpoch.current, identity = currentIdentity.current, context = epoch.current;
    const current = () => active.current && version === historySequence.current
      && authentication === authEpoch.current && identity === currentIdentity.current
      && context === epoch.current && now() < Date.parse(session.valid_until);
    setInspectedReceipt(null); setLookupError('');
    try {
      const value = await read<Receipts>('/receipts?key=' + encodeURIComponent(key), 'Receipts',
        AbortSignal.any([controller.signal, AbortSignal.timeout(4000)]));
      if (!current()) return;
      const found = value.items.find(row => row.idempotency_key === key);
      if (!found && value.items.length) throw Error('incompatible_contract');
      setInspectedReceipt(found ?? null); setLookupError(found ? '' : m.historyLookupEmpty);
    } catch (error) { if (current() && !controller.signal.aborted) { setLookupError(errorText(error));
      if (error instanceof ApiError && error.status === 403) identityFailure(); } }
  };
  const componentState = (item: Component) => item.valid_until && clock >= Date.parse(item.valid_until) ? 'STALE' : item.state;
  const financialMeta = snapshot?.components.find(c => c.name === 'financial');
  const financialStale = financialMeta ? componentState(financialMeta) !== 'AVAILABLE' : true;
  const supervisionMeta = snapshot?.components.find(c => c.name === 'supervision');
  const supervisionValid = supervisionMeta && componentState(supervisionMeta) === 'AVAILABLE';

  return <div className={s.shell}>
    <a href="#main" className={s.skip}>{m.skip}</a>
    <aside className={s.sidebar} aria-label="Workspace navigation">
      <a className={s.brand} href="/"><span className={s.mark}>P</span><span>PolySia<small>CONSOLE</small></span></a>
      <span className={s.navLabel}>{m.workspace}</span>
      <nav>{([m.overview, m.investigate, m.operate, m.evaluate, m.system] as const).map((name, i) => <button key={name}
        className={tab === name ? s.navActive : s.navButton} onClick={() => setTab(name)} aria-current={tab === name ? 'page' : undefined}>
        <span className={s.navIcon} aria-hidden="true">{['◫', '⌕', '↗', '◷', '◇'][i]}</span>{name}</button>)}
      </nav>
      <div className={s.sidebarFoot}><p>{m.operatingBoundary}</p><a href={example ? '/' : '/?example=1'}>{example ? m.retained : m.example}</a></div>
    </aside>
    <div className={s.workspace}>
      <header className={s.topbar}><div><span className={s.breadcrumb}>Workspace / </span><strong>{tab}</strong></div>
        <div className={s.identity}><span className={validIdentity ? s.dot : s.dotBad} />
          <span>{session?.role === 'reader' ? m.readOnly : validIdentity ? m.valid : m.unknown}</span>{identifier(session?.actor)}</div>
      </header>
      <section className={s.context} aria-label={m.scope}>
        <div><small>{m.run}</small>{identifier(snapshot?.context.scope.run)}</div>
        <div><small>{m.account}</small>{identifier(snapshot?.context.scope.account)}</div>
        <div><small>{m.configured}</small><strong>{snapshot?.context.configured_mode ?? m.unknown}</strong></div>
        <div><small>{m.observed}</small><Badge>{snapshot?.context.observed_mode ?? m.unknown}</Badge></div>
        <div><small>{m.dataset}</small><strong>{snapshot?.context.dataset ?? m.unknown}</strong></div>
        <div><small>{m.environment}</small><strong>{snapshot?.context.environment ?? m.unknown}</strong></div>
      </section>
      <div className={s.protective} role="region" aria-label={m.protective}>
        <span>{m.protective}</span>{actions.filter(a => a.protective && a.operation !== 'acquisition.drain').map(a =>
          <Button key={a.operation + a.target} variant="outline" disabled={!validIdentity || ['sending', 'uncertain', 'absent'].includes(commandState)}
            onClick={() => { setTab('Operate'); changeAction(a.operation + '|' + a.target); }}>{a.label} · {identifier(a.target)}</Button>)}
        {!actions.some(a => a.protective) && <span>{m.unavailable}</span>}
      </div>
      <main id="main" tabIndex={-1} className={s.main} aria-busy={refreshBusy}>
        <div className={s.pageHeading}><div><p className={s.eyebrow}>{m.eyebrow}</p>
          <h1>{tab === 'Overview' ? m.heading : tab === 'Investigate' ? m.investigateTitle : tab === 'Operate' ? m.operateTitle : tab === 'Evaluate' ? m.evaluateTitle : m.systemTitle}</h1>
          <p>{tab === 'Overview' ? m.subtitle : tab === 'Investigate' ? m.investigateSubtitle : tab === 'Operate' ? m.operateSubtitle : tab === 'Evaluate' ? m.evaluateSubtitle : m.systemSubtitle}</p></div>
          <Button className={s.secondaryButton} disabled={refreshBusy} onClick={() => { setWorkspaceRefresh(value => value + 1); void refresh(); }}>{m.refresh} ↻</Button>
        </div>
        {(authFailure || failure) && <div className={s.error} role="alert">{authFailure || failure}
          {authFailure && <Button onClick={() => void refresh()}>{m.renew}</Button>}</div>}
        {clockSkew && <p className={s.muted} role="status">{m.clockSkew}</p>}
        {example && <p role="status">{m.exampleNotice}</p>}
        {tab === 'Overview' && <>
          <section className={s.blocker} aria-label={m.attention}><span className={s.blockerIcon}>!</span><div>
            <strong>{m.attention}</strong><p>{snapshot?.blocker ?? m.loading}</p></div>
            <button onClick={() => setTab('Operate')}>{m.operate} →</button></section>
          <section className={s.metrics} aria-label="Exact financial amounts">
            {[[m.cash, snapshot?.financial?.cash], [m.exposure, snapshot?.financial?.exposure], [m.reserved, snapshot?.financial?.reserved]].map(([label, value]) =>
              <article key={label as string} className={s.metric}><p>{label as string}</p><Amount value={value as Money | undefined} />
                <small>{financialStale ? m.staleData : (value as Money | undefined)?.meaning ?? m.noEvidence}</small>
                <Badge alert={financialStale}>{financialMeta ? componentState(financialMeta) : m.unknown}</Badge></article>)}
          </section>
          <div className={s.twoColumns}>
            <section className={s.panel} aria-label={m.independent}><div className={s.panelHeading}><h2>{m.independent}</h2>
              <Badge alert={!supervisionValid || snapshot?.supervision.status === 'STOPPED'}>{supervisionValid ? snapshot?.supervision.status : m.unknown}</Badge></div>
              <p>{supervisionValid ? snapshot?.supervision.reason : m.staleData}</p><p className={s.muted}>{snapshot?.supervision.next_action ?? m.missing}</p>
              <button className={s.textButton} onClick={() => { setTab('Operate'); const stop = actions.find(a => a.operation === 'session.stop');
                if (stop) changeAction(stop.operation + '|' + stop.target); }}>{m.operate} →</button></section>
            <section className={s.panel}><div className={s.panelHeading}><h2>{m.authority}</h2><Badge>{financialStale ? m.unknown : snapshot?.financial?.authority_until && clock >= Date.parse(snapshot.financial.authority_until) ? 'EXPIRED' : snapshot?.financial?.authority ?? m.unknown}</Badge></div>
              <dl className={s.facts}><dt>{m.operational}</dt><dd>{snapshot?.financial?.status ?? m.unknown}</dd>
                <dt>{m.reconciliation}</dt><dd>{snapshot?.financial?.reconciliation ?? m.unknown}</dd>
                <dt>{m.economics}</dt><dd>{snapshot?.financial?.economics ?? m.unknown}</dd>
                <dt>{m.liability}</dt><dd>{snapshot?.financial?.unknown_orders ?? m.unknown}</dd>
                <dt>{m.accountObserved}</dt><dd><Timestamp value={snapshot?.financial?.account_observed_at} /></dd>
                <dt>{m.accountExpiry}</dt><dd><Timestamp value={snapshot?.financial?.account_valid_until} /></dd>
                <dt>{m.authorityExpires}</dt><dd><Timestamp value={snapshot?.financial?.authority_until} /></dd></dl><p className={s.muted}>{m.permit}</p><p className={s.muted}>{m.liabilitiesUnknown}</p></section>
          </div>
          <section className={s.panel}><div className={s.panelHeading}><h2>{m.freshness}</h2><small>{m.utc}</small></div>
            <div className={s.evidenceRows}>{snapshot?.components.map(item => <div key={item.name} className={s.evidenceRow}>
              <strong>{names[item.name]}</strong><Badge alert={componentState(item) !== 'AVAILABLE'}>{componentState(item)}</Badge>
              <span><Timestamp value={item.observed_at} locale={rtl ? 'fa-IR' : 'en-GB'} /><br />
                {item.observed_at ? clock >= Date.parse(item.observed_at) ? `${Math.floor((clock - Date.parse(item.observed_at)) / 1000)} ${m.secondsOld}` : m.futureTime : m.unknown}</span>
              <div><small>{item.reason}</small><details><summary>{m.validityDetails}</summary>
                <dl className={s.facts}><dt>{m.validUntil}</dt><dd><Timestamp value={item.valid_until} /></dd>
                  <dt>{m.run}</dt><dd>{identifier(item.scope.run)}</dd><dt>{m.generation}</dt><dd>{identifier(item.generation)}</dd></dl></details></div></div>)}</div>
            <p className={s.muted}>{m.provenance}</p>
            <details><summary>{m.scope}</summary><dl className={s.facts}><dt>{m.venue}</dt><dd>{identifier(snapshot?.context.scope.venue)}</dd>
              <dt>{m.environment}</dt><dd>{snapshot?.context.environment ?? m.unknown}</dd><dt>{m.generation}</dt><dd>{identifier(snapshot?.context.generation)}</dd></dl></details>
          </section>
        </>}
        {tab === 'Investigate' && <Investigation generation={snapshot?.context.generation ?? null} onIdentityFailure={identityFailure} />}
        {tab === 'Operate' && <>
          <section className={s.panel}><h2>{m.target}</h2><label className={s.label} htmlFor="operation">{m.target}</label>
            <select id="operation" className={s.input} value={chosen} onChange={e => changeAction(e.target.value)} disabled={!validIdentity || ['sending', 'uncertain', 'absent'].includes(commandState)}>
              <option value="">{actions.length ? m.chooseOperation : m.unavailable}</option>{actions.map(a => <option key={a.operation + a.target}
                value={a.operation + '|' + a.target}>{a.label} · {a.target}</option>)}</select>
            <p>{action?.impact ?? (actions.length ? m.chooseOperation : m.unavailable)}</p>
            <p className={s.muted}>{m.unavailableActions}</p>
            {(action?.arguments ?? []).map(field => <label className={s.label} key={field.name}>{field.label}
              {field.kind === 'choice' ? <select className={s.input} value={arguments_[field.name] ?? ''}
                disabled={['sending', 'uncertain', 'absent'].includes(commandState)} onChange={event => { invalidate(); setArguments({ ...arguments_, [field.name]: event.target.value }); }}>
                <option value="">{m.policyChoice}</option>{field.choices.map(choice => <option key={choice.value} value={choice.value}>{choice.label} · {choice.value}</option>)}</select>
              : <input className={s.input} type="datetime-local" step="1" disabled={['sending', 'uncertain', 'absent'].includes(commandState)}
                value={(arguments_[field.name] ?? '').replace(/Z$/, '')} onChange={event => { invalidate(); const next = { ...arguments_ };
                  if (event.target.value) next[field.name] = event.target.value + 'Z'; else delete next[field.name]; setArguments(next); }} />}</label>)}
            {!argumentsReady && <p className={s.muted} role="status">{m.argumentsRequired}</p>}
            <Button onClick={() => void makePreview()} disabled={!action || !argumentsReady || !validIdentity || ['sending', 'uncertain', 'absent', 'previewing'].includes(commandState)}>{m.preview}</Button>
            {commandError && <p role="alert" className={s.commandMessage}>{commandError}</p>}
            {intent && <p>{m.key}: {identifier(intent.idempotency_key)}</p>}
            {(commandState === 'uncertain' || commandState === 'absent') && intent && <Button onClick={() => void recover(intent.idempotency_key)}>{m.recover}</Button>}
            {commandState === 'absent' && preview && validIdentity && Date.parse(preview.expires_at) > clock
              && preview.identity === session?.identity && <Button onClick={() => void apply()}>{m.retry}</Button>}
            {receipt && <ReceiptView receipt={receipt} />}
          </section>
          <section className={s.panel}><h2>{m.history}</h2><p className={s.muted}>{m.requested}</p>
            {historyError && <p role="alert">{historyError}</p>}
            <form className={s.searchForm} onSubmit={e => { e.preventDefault(); void inspectReceipt(lookupKey); }}>
              <label className={s.label}>{m.receiptKey}<input className={s.input} value={lookupKey} maxLength={80} onChange={e => {
                historySequence.current += 1; historyRequest.current?.abort(); setInspectedReceipt(null); setLookupError(''); setLookupKey(e.target.value);
              }} /></label>
              <Button type="submit" disabled={!validIdentity || !lookupKey}>{m.lookup}</Button></form>
            {lookupError && <p role="status">{lookupError}</p>}
            {inspectedReceipt && <div role="region" aria-label={m.inspectedReceipt}><ReceiptView receipt={inspectedReceipt} /></div>}
            {history?.items.map(row => <ReceiptView key={row.idempotency_key} receipt={row} />)}
            {history?.next_cursor && <Button onClick={async () => {
              const authentication = authEpoch.current, identity = currentIdentity.current, version = epoch.current;
              const current = () => active.current && authentication === authEpoch.current
                && identity === currentIdentity.current && version === epoch.current && session !== null
                && now() < Date.parse(session.valid_until);
              try { const value = await read<Receipts>('/receipts?cursor=' + encodeURIComponent(historyCursor || history.next_cursor!), 'Receipts');
                if (current()) { setHistory(value); setHistoryCursor(value.next_cursor ?? ''); }
              } catch (error) { if (current()) { setHistoryError(m.historyUnavailable); if (error instanceof ApiError && error.status === 403) identityFailure(); } }
            }}>{m.next}</Button>}
          </section>
          <EvidenceWorkspace key={workspaceRefresh} panel="operate" generation={snapshot?.context.generation ?? null} identity={session?.identity ?? ''} clock={clock} onIdentityFailure={identityFailure} />
        </>}
        {(tab === 'Evaluate' || tab === 'System / Setup') && <EvidenceWorkspace key={tab + workspaceRefresh} panel={tab === 'Evaluate' ? 'evaluate' : 'system'}
          generation={snapshot?.context.generation ?? null} identity={session?.identity ?? ''} clock={clock} onIdentityFailure={identityFailure} />}
        {tab === 'Evaluate' && <section className={s.panel} aria-label={m.exports}><h2>{m.exports}</h2>
          {example ? <p>{m.exampleNoExports} <a href="/">{m.retained}</a></p> : <><p><a href="/api/report">{m.reportDownload}</a></p><p><a href="/download/comparison.csv">{m.comparisonDownload}</a></p></>}</section>}
        {tab === 'Evaluate' && history?.items.filter(row => (row.tables ?? []).length > 0).map(row => <ReceiptView key={row.idempotency_key} receipt={row} />)}
        <footer className={s.footer}><span>{m.permit}</span><label>{m.locale} <input type="checkbox" checked={rtl} onChange={e => setRtl(e.target.checked)} /> fa-IR / RTL</label>
          {rtl && <span lang="fa" dir="rtl">{m.persianFixture}</span>}</footer>
      </main>
    </div>
    <Modal opened={preview !== null && commandState === 'preview'} onClose={() => { invalidate(); rememberIntent(null); }}
      title={m.previewTitle} centered returnFocus transitionProps={{ duration: 0 }} closeButtonProps={{ 'aria-label': m.close }}>
      {preview && <><p>{preview.impact}</p><dl className={s.facts}><dt>{m.actor}</dt><dd>{identifier(preview.actor)}</dd>
        <dt>{m.target}</dt><dd>{identifier(preview.operation)} · {identifier(preview.target)}</dd><dt>{m.revision}</dt><dd>{preview.expected_revision}</dd>
        <dt>{m.expires}</dt><dd><Timestamp value={preview.expires_at} /></dd></dl>
        <dl className={s.facts}>{(preview.arguments ?? []).map(fact => <div key={fact.label}><dt>{fact.label}</dt><dd>{identifier(fact.value)}</dd></div>)}</dl>
        <p className={s.muted}>{m.permit}</p><Button onClick={() => void apply()} disabled={!validIdentity}>{m.confirm}</Button></>}
    </Modal>
  </div>;
}

function ReceiptView({ receipt }: { receipt: Receipt }) {
  return <article className={s.receipt} aria-label={m.history}><div className={s.panelHeading}>
    <strong>{receipt.operation}</strong><Badge alert={receipt.effect === 'UNKNOWN'}>{receipt.phase}</Badge></div>
    <p>{identifier(receipt.target)}</p><p>{m.effect}: <strong>{receipt.effect}</strong> · {m.revision}: {receipt.revision}</p>
    <small>{m.key}: {identifier(receipt.idempotency_key)}</small>
    {receipt.effect === 'UNKNOWN' && <p className={s.commandMessage}>{m.unresolved}</p>}{receipt.reason && <p>{receipt.reason}</p>}
    <dl className={s.facts}>{(receipt.facts ?? []).map(fact => <div key={fact.label}><dt>{fact.label}</dt><dd>{identifier(fact.value)}</dd></div>)}</dl>
    {(receipt.tables ?? []).map(table => <div className={s.tableRegion} key={table.title} role="region" tabIndex={0} aria-label={table.title}>
      <table><caption>{table.title}</caption><thead><tr>{table.columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
        <tbody>{table.rows.map((cells, i) => <tr key={i}>{cells.map((value, j) => <td key={j}><bdi dir={valueDirection(value)}>{value ?? m.unknown}</bdi></td>)}</tr>)}</tbody></table></div>)}
    {receipt.download && <p><a href={receipt.download}>{m.receiptDownload}</a></p>}</article>;
}

function Investigation({ generation, onIdentityFailure }: { generation: string | null; onIdentityFailure: () => void }) {
  const [kind, setKind] = useState('order');
  const [query, setQuery] = useState('');
  const [state, setState] = useState('');
  const [source, setSource] = useState('');
  const [page, setPage] = useState<Page | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState('');
  const epoch = useRef(0);
  const reading = useRef<AbortController | null>(null);
  const boundedSignal = () => { reading.current?.abort(); reading.current = new AbortController();
    return AbortSignal.any([reading.current.signal, AbortSignal.timeout(4000)]); };
  const load = useCallback(async (cursor = '') => {
    const version = ++epoch.current;
    try { const value = await read<Page>('/records?' + new URLSearchParams({ kind, q: query, state, source, cursor }), 'Page', boundedSignal());
      if (version === epoch.current) { setPage(value); setError(''); setDetail(null); }
    } catch (err) { if (version === epoch.current) { setError(errorText(err));
      if (err instanceof ApiError && err.status === 403) onIdentityFailure(); } }
  }, [kind, query, state, source, onIdentityFailure]);
  useEffect(() => { setPage(null); setDetail(null); epoch.current += 1;
    // New generation requires a visible explicit list refresh; never append incompatible pages.
    setError(m.cursor);
    return () => { epoch.current += 1; reading.current?.abort(); };
  }, [generation, kind]);
  return <section className={s.panel}>
    <form className={s.searchForm} onSubmit={e => { e.preventDefault(); void load(); }}>
      <label className={s.label}>{m.kind}<select className={s.input} value={kind} onChange={e => { setKind(e.target.value); setQuery(''); setState(''); }}>
        <option value="order">{m.orders}</option><option value="wallet">{m.wallets}</option><option value="position">{m.positions}</option></select></label>
      <label className={s.label}>{m.search}<input className={s.input} type="search" maxLength={128} value={query} onChange={e => { epoch.current++; setQuery(e.target.value); }} /></label>
      <label className={s.label}>{m.filter}<input className={s.input} maxLength={64} value={state} onChange={e => { epoch.current++; setState(e.target.value); }} /></label>
      {kind === 'wallet' && <label className={s.label}>{m.sourceFilter}<input className={s.input} maxLength={128} value={source} onChange={e => { epoch.current++; setSource(e.target.value); }} /></label>}
      <Button type="submit">{m.searchButton}</Button></form>
    {error && <p role="status">{error}</p>}
    <div className={s.tableRegion} tabIndex={0} role="region" aria-label={m.investigate}>
      <table><thead><tr>{[m.identity, m.state, m.side, m.quantity, m.price].map(v => <th key={v}>{v}</th>)}</tr></thead>
        <tbody>{page?.items.map(row => <tr key={row.identity}><td><button className={s.recordButton} onClick={async () => {
          const version = ++epoch.current;
          try { const result = await read<Detail>('/detail?' + new URLSearchParams({ kind, identity: row.identity, generation: page.generation }), 'Detail');
            if (version === epoch.current) setDetail(result); } catch (err) { if (version === epoch.current) { setError(errorText(err)); if (err instanceof ApiError && err.status === 403) onIdentityFailure(); } }
        }}>{identifier(row.identity)}</button></td><td><Badge>{row.state}</Badge></td><td>{row.side ?? m.unknown}</td>
          <td><Amount value={row.quantity} /></td><td><Amount value={row.price} /></td></tr>)}</tbody></table>
      {page?.items.length === 0 && <p>{m.empty}</p>}</div>
    <div className={s.pagination}><span>{page ? `${page.items.length} / ${page.total} ${m.observations}` : m.noEvidence}</span>
      <Button className={s.secondaryButton} onClick={() => void load()}>{m.reset}</Button>
      <Button disabled={!page?.next_cursor || !!error} onClick={() => void load(page?.next_cursor ?? '')}>{m.next}</Button></div>
    {detail && <section className={s.detail} aria-label={m.details}><div className={s.panelHeading}><h2>{m.details}</h2><Button onClick={() => setDetail(null)}>{m.close}</Button></div>
      <dl className={s.facts}>{[[m.identity, detail.record.identity], [m.state, detail.record.state], [m.token, detail.record.token],
        [m.fill, detail.record.fill_state], [m.settlement, detail.record.settlement_state], [m.reason, detail.record.reason],
        [m.updated, stamp(detail.record.updated_at)]].map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{identifier(value)}</dd></div>)}</dl>
      <dl className={s.facts}>{(detail.record.facts ?? []).map((fact, i) => <div key={fact.label + i}><dt>{fact.label}</dt><dd>{identifier(fact.value)}</dd></div>)}</dl>
      <h3>{m.evidenceLinks}</h3>{(detail.record.links ?? []).map(link => <Button key={link.kind + link.identity}
        onClick={async () => { const version = ++epoch.current;
          try { const result = await read<Detail>('/detail?' + new URLSearchParams({ kind: link.kind, identity: link.identity, generation: detail.generation }), 'Detail', boundedSignal());
            if (version === epoch.current) setDetail(result); } catch (err) { if (version === epoch.current) { setError(errorText(err)); if (err instanceof ApiError && err.status === 403) onIdentityFailure(); } }
        }}>{link.label} · {identifier(link.identity)}</Button>)}
      <p>{detail.trace}</p><p className={s.muted}>{m.exact}</p>
      {detail.record.kind === 'position' && <p className={s.muted}>{m.redemptionBoundary}</p>}</section>}
  </section>;
}
