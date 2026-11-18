import { useEffect, useRef, useState } from 'react';
import { Button } from '@mantine/core';
import { ApiError, post, read } from './client';
import type { Session, ShadowRunDetail, Watchlist, WatchlistRun, WatchlistRunPage } from './contract.generated';
import s from './Leaderboard.module.css';

const units = { minutes: 60, hours: 3600, days: 86400 } as const;
const local = (stamp: string) => new Date(stamp).toLocaleString();
function compact(amount: string) {
  const [whole = '', fraction] = amount.split('.');
  if (!/^-?\d+$/.test(whole) || (fraction && !/^\d+$/.test(fraction))) return amount;
  const trimmed = fraction?.replace(/0+$/, '') ?? '';
  if (whole.replace('-', '') === '0' && trimmed && !/[1-9]/.test(trimmed.slice(0, 4))) return amount;
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  const value = grouped + (trimmed ? '.' + trimmed.slice(0, 4) : '');
  return trimmed.length > 4 ? '≈ ' + value : value;
}
const errorCopy: Record<string, string> = {
  shadow_busy: 'A paper test is already running. Open Paper tests to see its status.',
  shadow_storage_low: 'There is too little disk space for a new test. Ask the server administrator to free space.',
  shadow_cohort_size: 'Choose a supported number of distinct wallets.',
  watchlist_revision_changed: 'This watchlist changed. Reopen it and confirm your selection.',
  watchlist_missing: 'This watchlist is no longer available. Reopen your watchlists.',
  shadow_request_id_conflict: 'This request ID was already used. Check Paper tests for its result.',
};

type Launch = {
  run_id: string;
  list_id: string | null;
  list_revision: number | null;
  duration_seconds: number;
  wallets: string[];
};

export function WatchlistShadow({ session, list, onDone }: {
  session: Session;
  list: Watchlist | null;
  onDone: () => void;
}) {
  const [runs, setRuns] = useState<WatchlistRunPage | null>(null);
  const [amount, setAmount] = useState('2');
  const [unit, setUnit] = useState<keyof typeof units>('days');
  const [wallets, setWallets] = useState(list?.wallets ?? []);
  const [pending, setPending] = useState(false);
  const [uncertain, setUncertain] = useState<Launch | null>(null);
  const [message, setMessage] = useState('');
  const [offset, setOffset] = useState(0);
  const [ended, setEnded] = useState<string | null>(null);
  const requestInFlight = useRef(false);
  const done = useRef<HTMLHeadingElement>(null);
  const duration = Number(amount) * units[unit];
  const validDuration = !!runs && Number.isInteger(duration) &&
    duration >= runs.min_duration_seconds && duration <= runs.max_duration_seconds;
  const validWallets = !!runs && wallets.length > 0 && wallets.length <= runs.max_wallets;

  useEffect(() => {
    let active = true;
    const load = () => {
      if (requestInFlight.current) return;
      void read<WatchlistRunPage>('/watchlist-runs?offset=' + offset, 'WatchlistRunPage')
        .then(value => { if (active && !requestInFlight.current) {
          setRuns(value);
          setMessage(text => text === 'Could not read the tests. This view retries automatically.' ? '' : text);
        } })
        .catch(() => { if (active && !requestInFlight.current) {
          setMessage('Could not read the tests. This view retries automatically.');
        } });
    };
    load();
    const timer = window.setInterval(load, 15_000);
    return () => { active = false; window.clearInterval(timer); };
  }, [offset]);

  useEffect(() => {
    if (!list) done.current?.focus();
  }, [list, runs !== null]);

  async function mutate(path: string, data: Launch | { run_id: string }) {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    setPending(true);
    setMessage('');
    const launch = 'wallets' in data;
    try {
      if (launch && uncertain) {
        const state = await read<WatchlistRunPage>('/watchlist-runs', 'WatchlistRunPage');
        if (state.items.some(run => run.id === data.run_id)) {
          setRuns(state);
          onDone();
          return;
        }
      }
      const result = await post<WatchlistRunPage>(path, 'WatchlistRunPage',
        { ...data, identity: session.identity }, session.csrf);
      setOffset(0);
      setRuns(result);
      setUncertain(null);
      if (launch) onDone();
      else setEnded(data.run_id);
    } catch (error) {
      const reason = error instanceof ApiError ? errorCopy[error.message] : undefined;
      if (reason) {
        setUncertain(null);
        setMessage(reason);
      } else {
        setMessage(launch
          ? 'Start is unconfirmed. Check and retry the same request to avoid creating a duplicate.'
          : 'The end request is unconfirmed. Check the refreshed status, then retry if the test is still running.');
        if (launch) setUncertain(data);
      }
    } finally {
      requestInFlight.current = false;
      setPending(false);
    }
  }

  return <section className={s.watchlistForm} aria-label="Paper tests (Shadow)">
    {message && <p role="status">{message}</p>}
    {list ? <form className={s.watchlistForm} noValidate onSubmit={event => {
      event.preventDefault();
      if (uncertain) {
        void mutate('/watchlist-runs', uncertain);
      } else if (validDuration && validWallets && !runs?.busy && !runs?.storage_low) {
        void mutate('/watchlist-runs', {
          run_id: crypto.randomUUID().replaceAll('-', ''), list_id: list.id || null,
          list_revision: list.id ? list.revision : null, duration_seconds: duration, wallets,
        });
      }
    }}>
      <strong>{list.name}</strong>
      <span>Paper test with virtual funds and public prices.</span>
      <fieldset disabled={pending || uncertain !== null} className={s.shadowFields}>
        <legend>Wallets for this test</legend>
        <p>{wallets.length} selected{runs ? ' · up to ' + runs.max_wallets : ''}</p>
        {runs && !validWallets && <p role="status">Choose 1–{runs.max_wallets} wallets for this test.</p>}
        <div className={s.shadowWallets}>{list.wallets.map(address =>
          <label key={address}><input type="checkbox" checked={wallets.includes(address)}
            onChange={event => {
              const checked = event.target.checked;
              setWallets(current => checked ? [...current, address] : current.filter(item => item !== address));
            }} /> <code title={address}>{address.slice(0, 10)}…{address.slice(-6)}</code></label>
        )}</div>
      </fieldset>
      <fieldset disabled={pending || uncertain !== null} className={s.shadowFields}>
        <legend>Duration</legend>
        {runs && <small id="paper-duration-range">Choose {runs.min_duration_seconds / 60} minutes to {runs.max_duration_seconds / 86400} days.</small>}
        <div className={s.actions}>
          <Button type="button" variant="default" onClick={() => { setAmount('15'); setUnit('minutes'); }}>15 minutes</Button>
          <Button type="button" variant="default" onClick={() => { setAmount('2'); setUnit('hours'); }}>2 hours</Button>
          <Button type="button" variant="default" onClick={() => { setAmount('2'); setUnit('days'); }}>2 days</Button>
        </div>
        <div className={s.actions}>
          <label>Duration<input type="number" min="1" required value={amount}
            aria-invalid={!!runs && !validDuration} aria-describedby="paper-duration-range"
            onChange={event => setAmount(event.target.value)} /></label>
          <label>Unit<select aria-label="Duration unit" value={unit}
            onChange={event => setUnit(event.target.value as keyof typeof units)}>
            <option value="minutes">Minutes</option><option value="hours">Hours</option><option value="days">Days</option>
          </select></label>
        </div>
        {validDuration && <p>Estimated end {local(new Date(Date.now() + duration * 1000).toISOString())}</p>}
      </fieldset>
      {runs && <small>{runs.starting_cash} virtual USDC per wallet, up to {runs.maximum_fill} USDC per simulated trade.
        Modeled fee {Number(runs.fee_bps) / 100}%.</small>}
      {runs?.busy && <p role="status">A paper test is running. Open Paper tests to view it.</p>}
      {runs?.storage_low && <p role="status">{errorCopy.shadow_storage_low}</p>}
      <Button type="submit" disabled={pending || (!uncertain &&
        (!validDuration || !validWallets || runs?.busy || runs?.storage_low))}>
        {uncertain ? 'Check and retry start' : 'Start Shadow'}
      </Button>
    </form> : <>
      {!runs ? <p>Loading tests…</p> : <>
        {offset === 0 && <><h3 tabIndex={-1} ref={done}>Active test</h3>{runs.items.some(run => run.status === 'RUNNING')
          ? runs.items.filter(run => run.status === 'RUNNING').map(run => <RunCard key={run.id} run={run}
            stop={pending ? undefined : () => {
              if (window.confirm('End this paper test and keep its report?')) {
                void mutate('/watchlist-runs/cancel', { run_id: run.id });
              }
            }} />)
          : <p>{runs.busy ? 'Another operator has a test running.' : 'No active paper test.'}</p>}</>}
        <h3>History</h3>
        {runs.items.filter(run => run.status !== 'RUNNING').map(run =>
          <RunCard key={run.id} run={run} show={ended === run.id} />)}
        {!runs.items.some(run => run.status !== 'RUNNING') && <p>No completed paper tests on this page.</p>}
        <div className={s.actions}>
          {offset > 0 && <Button variant="default" onClick={() => { setRuns(null); setOffset(0); }}>Newest tests</Button>}
          {runs.next_offset !== null && <Button variant="default" onClick={() => {
            setOffset(runs.next_offset ?? 0); setRuns(null);
          }}>Older tests</Button>}
        </div>
      </>}
    </>}
  </section>;
}

function RunCard({ run, stop, show }: { run: WatchlistRun; stop?: () => void; show?: boolean }) {
  const running = run.status === 'RUNNING';
  const fills = run.wallets.reduce((sum, wallet) => sum + wallet.fills, 0);
  const skipped = run.wallets.reduce((sum, wallet) => sum + wallet.skipped, 0);
  const open = run.wallets.reduce((sum, wallet) => sum + wallet.open_positions, 0);
  const valued = run.wallets.reduce((sum, wallet) => sum + wallet.valued_positions, 0);
  const hasMark = run.wallets.some(wallet => wallet.marked_positions > 0);
  const closed = run.wallets.every(wallet => wallet.closed_positions !== null)
    ? run.wallets.reduce((sum, wallet) => sum + (wallet.closed_positions ?? 0), 0) : null;
  const coverage = {
    observing: 'Observation is in progress.',
    covered: 'The source was checked through the end of the test.',
    incomplete: 'Some of the test period has no verified observations.',
    none: 'The source supplied no verified observations.',
  };
  return <details open={running || show || undefined} className={s.shadowCard}>
    <summary>{run.name} · {running ? 'Running' : run.end_reason === 'manual' || run.status === 'CANCELLED'
      ? 'Ended early' : 'Finished'} · {run.wallets.length} {run.wallets.length === 1 ? 'wallet' : 'wallets'}</summary>
    <div className={s.watchlistForm}>
      <small>Paper test · virtual funds</small>
      <p>{fills} simulated {fills === 1 ? 'trade' : 'trades'} · {skipped} skipped · {open} open positions
        {closed === null ? '' : ' · ' + closed + ' closed positions'}</p>
      <p>Gain or loss from simulated sales <strong>{compact(run.realized)} USDC</strong></p>
      {open > 0 && <p>{open - valued} of {open} open positions lack a full ending price.</p>}
      {!running && <>
        <p>{run.equity === null ? 'Total paper balance at the end is unavailable.'
          : 'Estimated paper balance from observed activity ' + compact(run.equity) + ' USDC.'}</p>
        {run.net_pnl !== null && <p>Estimated total gain or loss <strong>{compact(run.net_pnl)} USDC</strong></p>}
        {hasMark && <p>Estimated gain or loss on priced shares {compact(run.marked_pnl)} USDC.</p>}
        {open > valued && <p>Unpriced shares cost {compact(run.unvalued_cost)} USDC.</p>}
      </>}
      <p>{coverage[run.coverage]}</p>
      {stop && <Button variant="default" onClick={stop}>End test and see results</Button>}
      <details>
        <summary>Wallets and exact evidence</summary>
        <p>Started {local(run.started_at)} · scheduled end {local(run.ends_at)}
          {run.cutoff_at ? ' · ended ' + local(run.cutoff_at) : ''}</p>
        <p>Each wallet uses a separate virtual balance. Combined estimates do not represent a joint sale.</p>
        <p>Model {run.model} · exact realized {run.realized} USDC
          {run.equity === null ? '' : ' · exact paper balance ' + run.equity + ' USDC'}</p>
        <ul>{run.wallets.map(wallet => <li key={wallet.address}><div>
          <code>{wallet.address}</code>
          <p>{wallet.fills} trades · {wallet.skipped} skipped · {wallet.open_positions} open</p>
          <p>Cash {wallet.cash} · open cost {wallet.open_cost} · covered value {wallet.marked_value}
            {' · gain or loss on covered shares '}{wallet.marked_pnl} · fees {wallet.fees} · slippage {wallet.slippage} USDC</p>
          <small>{wallet.observations ? 'Observed through ' + local(wallet.observed_through) : 'No observations'}
            {' · ' + wallet.read_errors + ' read errors'}
            {wallet.gaps.length ? ' · ' + wallet.gaps.map(gap => gap.replaceAll('_', ' ')).join(', ') : ''}</small>
          <WalletEvidence run={run.id} wallet={wallet.address} />
        </div></li>)}</ul>
      </details>
    </div>
  </details>;
}

function WalletEvidence({ run, wallet }: { run: string; wallet: string }) {
  const [data, setData] = useState<ShadowRunDetail | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState(false);
  async function load(offset: number) {
    setPending(true);
    setError(false);
    try {
      setData(await read<ShadowRunDetail>(
        '/watchlist-runs/detail?run_id=' + run + '&wallet=' + wallet + '&offset=' + offset, 'ShadowRunDetail',
      ));
    } catch { setError(true); } finally { setPending(false); }
  }
  return <details onToggle={event => { if (event.currentTarget.open && !pending) void load(0); }}>
    <summary>Positions and trade evidence</summary>
    {pending && <p role="status">Loading evidence…</p>}
    {error && <Button variant="default" onClick={() => void load(0)}>Retry evidence</Button>}
    {data && <>
      <p>Open positions on this page</p>
      <ul>{data.positions.map(position => <li key={position.outcome}><div>
        <code>{position.outcome}</code>
        <p>{position.quantity} shares · acquisition cost {position.cost} USDC</p>
        {position.value === null ? <p>Ending price unavailable.</p>
          : <p>{position.marked_quantity} shares priced · {position.value} USDC net of {position.fee}
            {' · '}{position.source}{position.quote_at && ' · quoted ' + local(position.quote_at)}
            {position.received_at && ' · received ' + local(position.received_at)}</p>}
      </div></li>)}</ul>
      <p>Trade decisions on this page</p>
      <ul>{data.events.map(item => <li key={item.id}><div>
        <strong>{item.reason.replaceAll('_', ' ')}</strong>
        <p>{item.side} {item.quantity} {item.price ? '@ ' + item.price : ''} {item.signal_at && local(item.signal_at)}</p>
        <code>{item.id}</code>
        {item.notional && <p>Notional {item.notional} · fee {item.fee} · slippage {item.slippage}
          {' · realized '}{item.realized} USDC</p>}
        {item.quote_at && <small>Quoted {local(item.quote_at)}
          {item.quote_received_at && ' · received ' + local(item.quote_received_at)}</small>}
      </div></li>)}</ul>
      {data.next_offset !== null && <Button variant="default" disabled={pending}
        onClick={() => void load(data.next_offset ?? 0)}>Next evidence</Button>}
    </>}
  </details>;
}
