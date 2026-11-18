import { useEffect, useState } from 'react';
import { Button } from '@mantine/core';
import { post, read } from './client';
import type { Session, Watchlist, WatchlistRunPage } from './contract.generated';
import s from './Leaderboard.module.css';

const units = { minutes: 60, hours: 3600, days: 86400 } as const;
const local = (stamp: string) => new Date(stamp).toLocaleString();

export function WatchlistShadow({ session, list, onDone }: {
  session: Session;
  list: Watchlist | null;
  onDone: () => void;
}) {
  const [runs, setRuns] = useState<WatchlistRunPage | null>(null);
  const [amount, setAmount] = useState('2');
  const [unit, setUnit] = useState<keyof typeof units>('days');
  const [requestId] = useState(() => crypto.randomUUID().replaceAll('-', ''));
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState('');
  const duration = Number(amount) * units[unit];
  const valid = runs && Number.isInteger(duration) &&
    duration >= runs.min_duration_seconds && duration <= runs.max_duration_seconds;

  useEffect(() => {
    let active = true;
    const load = () => { void read<WatchlistRunPage>('/watchlist-runs', 'WatchlistRunPage')
      .then(value => { if (active) setRuns(value); })
      .catch(() => { if (active) setMessage('Could not read the runs. Keep this panel open to retry.'); }); };
    load();
    const timer = window.setInterval(load, 15_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  async function mutate(path: string, data: object) {
    setPending(true);
    setMessage('');
    try {
      const result = await post<WatchlistRunPage>(path, 'WatchlistRunPage',
        { ...data, identity: session.identity }, session.csrf);
      setRuns(result);
      onDone();
    } catch {
      setMessage('Could not confirm the request. Check whether a run is already active, then retry.');
    } finally { setPending(false); }
  }

  return <section className={s.watchlistForm} aria-label="Watchlist Shadow">
    {message && <p role="status">{message}</p>}
    {list ? <form className={s.watchlistForm} onSubmit={event => {
      event.preventDefault();
      if (valid) void mutate('/watchlist-runs', {
        run_id: requestId, list_id: list.id, list_revision: list.revision, duration_seconds: duration,
      });
    }}>
      <strong>{list.name} · {list.wallets.length} wallets</strong>
      <span>Simulates with public order books. No real orders or funds are used.</span>
      <div className={s.actions}>
        <Button type="button" variant="default" onClick={() => { setAmount('2'); setUnit('hours'); }}>2 hours</Button>
        <Button type="button" variant="default" onClick={() => { setAmount('2'); setUnit('days'); }}>2 days</Button>
        <Button type="button" variant="default" onClick={() => { setAmount('4'); setUnit('days'); }}>4 days</Button>
      </div>
      <div className={s.actions}>
        <label>Duration<input type="number" min="1" required value={amount}
          onChange={event => setAmount(event.target.value)} /></label>
        <label>Unit<select aria-label="Duration unit" value={unit}
          onChange={event => setUnit(event.target.value as keyof typeof units)}>
          <option value="minutes">Minutes</option><option value="hours">Hours</option>
          <option value="days">Days</option>
        </select></label>
      </div>
      {runs && <small>Choose {runs.min_duration_seconds / 60} minutes to {runs.max_duration_seconds / 86400} days.
        Up to {runs.max_wallets} wallets per run.</small>}
      {valid && <span>Estimated end {local(new Date(Date.now() + duration * 1000).toISOString())}</span>}
      <small>100 virtual USDC per wallet, up to 5 USDC per fill with a modeled 2% fee.
        Missing books and late signals are skipped.</small>
      <Button type="submit" disabled={pending || !valid || !runs ||
        !list.wallets.length || list.wallets.length > runs.max_wallets}>Start Shadow</Button>
    </form> : <div className={s.watchlistForm}>
      {!runs ? <p>Loading runs…</p> : !runs.items.length ? <p>No Shadow runs yet.</p> :
        runs.items.map(run => <details key={run.id}>
          <summary>{run.name} · {run.status} · {run.wallets.length} wallets</summary>
          <div className={s.watchlistForm}>
            <p>Started {local(run.started_at)} · scheduled end {local(run.ends_at)}</p>
            <p>Realized simulated P&L {run.realized} USDC. {run.equity === null
              ? 'Total equity is unavailable while positions lack a verified ending value.'
              : 'Virtual equity ' + run.equity + ' USDC.'}</p>
            <ul>{run.wallets.map(wallet => <li key={wallet.address}>
              <div><code title={wallet.address}>{wallet.address.slice(0, 10)}…{wallet.address.slice(-6)}</code>
                <div>{wallet.fills} fills · {wallet.skipped} skipped · {wallet.open_positions} open</div>
                <div>Fees {wallet.fees} · slippage {wallet.slippage} · realized {wallet.realized} USDC</div>
                <small>{wallet.observations ? 'Observed through ' + local(wallet.observed_through) : 'No observations yet'}
                  {' · ' + wallet.read_errors + ' read errors'}</small></div>
            </li>)}</ul>
            {run.status === 'RUNNING' && <Button variant="default" disabled={pending}
              onClick={() => { if (window.confirm('Stop this run and keep its results?'))
                void mutate('/watchlist-runs/cancel', { run_id: run.id }); }}>Stop run</Button>}
          </div>
        </details>)}
    </div>}
  </section>;
}
