import { useEffect, useState } from 'react';
import { Button, Modal } from '@mantine/core';
import { ApiError, read } from './client';
import type {
  BenchmarkSummary, LeaderboardBenchmarks, LeaderboardComparison, LeaderboardPage,
  LeaderboardWallet,
} from './contract.generated';
import { Badge } from './design/Primitives';
import s from './Leaderboard.module.css';
import consoleStyles from './Console.module.css';

const count = (value: number) => value.toLocaleString('en-US');
const stamp = (value: string) => new Intl.DateTimeFormat('en-GB', {
  day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  timeZone: 'UTC',
}).format(new Date(value)) + ' UTC';
const shortWallet = (wallet: string) => wallet.slice(0, 8) + '…' + wallet.slice(-5);
const accessDenied = (reason: unknown) => reason instanceof ApiError && [401, 403].includes(reason.status);
const incompatible = (reason: unknown) => reason instanceof Error && reason.message === 'incompatible_contract';
const explanation = (reason: string | null) => {
  if (reason === 'http_429') return 'The provider limited requests.';
  if (reason === 'network_unavailable' || /^http_5/.test(reason ?? '')) return 'The provider was unavailable.';
  if (reason === 'budget_exhausted' || reason === 'page_budget_exhausted') return 'The collection limit was reached.';
  return 'The latest collection could not be verified.';
};

export function Leaderboard({ onIdentityFailure }: { onIdentityFailure: () => void }) {
  const [period, setPeriod] = useState('month');
  const [ranking, setRanking] = useState('PNL');
  const [category, setCategory] = useState('overall');
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');
  const [pagination, setPagination] = useState({ offset: 0, generation: null as string | null });
  const [reload, setReload] = useState(0);
  const [active, setActive] = useState<{ key: string; page: LeaderboardPage } | null>(null);
  const [references, setReferences] = useState<LeaderboardBenchmarks | null>(null);
  const [referenceError, setReferenceError] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(true);
  const [wallet, setWallet] = useState<string | null>(null);
  const [comparison, setComparison] = useState<BenchmarkSummary | null>(null);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const scope = new URLSearchParams({ period, ranking, category }).toString();
  const request = new URLSearchParams({
    period, ranking, category, q: query, offset: String(pagination.offset),
  });
  if (pagination.generation !== null) request.set('generation', pagination.generation);
  const key = request.toString();
  const snapshot = active?.key === key ? active.page : null;

  useEffect(() => {
    const controller = new AbortController();
    setBusy(true);
    setError('');
    void read<LeaderboardPage>('/leaderboard?' + key, 'LeaderboardPage',
      AbortSignal.any([controller.signal, AbortSignal.timeout(4000)])).then(page => {
      if (!controller.signal.aborted) setActive({ key, page });
    }).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      if (accessDenied(reason)) onIdentityFailure();
      else if (incompatible(reason)) {
        setActive(null); setWallet(null); setError('Leaderboard data is incompatible with this Console version.');
      }
      else if (reason instanceof ApiError && reason.status === 410) setError('A new board is available. Reload to start from page one.');
      else setError('Could not load the board. Try reloading.');
    }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    return () => controller.abort();
  }, [key, reload, onIdentityFailure]);

  useEffect(() => {
    const controller = new AbortController();
    setReferenceError(false);
    void read<LeaderboardBenchmarks>('/leaderboard/benchmarks', 'LeaderboardBenchmarks',
      AbortSignal.any([controller.signal, AbortSignal.timeout(4000)])).then(value => {
      if (!controller.signal.aborted) setReferences(value);
    }).catch((reason: unknown) => {
      if (controller.signal.aborted) return;
      if (accessDenied(reason)) onIdentityFailure();
      else {
        if (incompatible(reason)) { setReferences(null); setComparison(null); }
        setReferenceError(true);
      }
    });
    return () => controller.abort();
  }, [reload, onIdentityFailure]);

  useEffect(() => {
    if (pagination.generation !== null) return;
    const reader = window.setInterval(() => {
      if (document.visibilityState === 'visible') setReload(value => value + 1);
    }, 60_000);
    return () => window.clearInterval(reader);
  }, [pagination.generation]);

  const resetPage = () => { setPagination({ offset: 0, generation: null }); setWallet(null); };
  const refresh = () => { resetPage(); setReload(value => value + 1); };
  const next = (offset: number) => {
    setWallet(null);
    setPagination({ offset, generation: snapshot?.generation ?? null });
  };
  const basis = period === 'all' ? 'Lifetime realized P&L' : 'Marked P&L, net of flows';

  return <div className={s.layout}>
    <section className={s.board} aria-label="Polymarket leaderboard">
      <header className={s.boardHeader}>
        <div><h2>Trader rankings</h2><p>{basis} · Polymarket</p></div>
        <div className={s.actions}>
          <a className={s.coverageLink} href="#leaderboard-coverage">Reference coverage ↓</a>
          <Button className={consoleStyles.secondaryButton} onClick={refresh} disabled={busy}>Reload data</Button>
        </div>
      </header>
      <div className={s.summary}>
        <div><span>Wallet bank</span><strong>{snapshot ? count(snapshot.bank_count) : '—'}</strong></div>
        <div><span>Wallets on this board</span><strong>{snapshot?.fetched_at ? count(snapshot.board_count) : '—'}</strong></div>
        <div><span>Board captured</span><strong className={s.date}>{snapshot?.fetched_at ? stamp(snapshot.fetched_at) : '—'}</strong></div>
      </div>
      <button type="button" className={s.filterToggle} aria-controls="leaderboard-filters"
        aria-expanded={filtersOpen} onClick={() => setFiltersOpen(value => !value)}>
        <strong>Search and filters</strong><span>{period === 'all' ? 'All time' : period} · {ranking === 'PNL' ? 'P&L' : 'Volume'} · {category}{query && ' · Search active'}</span>
      </button>
      <form id="leaderboard-filters" className={s.controls} data-expanded={filtersOpen} onSubmit={event => {
        event.preventDefault(); resetPage(); setQuery(search.trim());
      }}>
        <label>Period<select value={period} onChange={event => {
          const value = event.target.value;
          setPeriod(value); if (value !== 'month') setCategory('overall'); resetPage();
        }}>
          <option value="day">Day</option><option value="week">Week</option>
          <option value="month">Month</option><option value="all">All time</option>
        </select></label>
        <label>Rank by<select value={ranking} onChange={event => { setRanking(event.target.value); resetPage(); }}>
          <option value="PNL">P&L</option><option value="VOLUME">Volume</option>
        </select></label>
        <label>Category<select value={category} disabled={period !== 'month'}
          onChange={event => { setCategory(event.target.value); resetPage(); }}>
          <option value="overall">Overall</option><option value="sports">Sports</option>
          <option value="politics">Politics</option><option value="crypto">Crypto</option>
        </select></label>
        <label className={s.search}>Search wallet bank<input value={search} type="search" maxLength={160}
          placeholder="Name or wallet address" onChange={event => {
            setSearch(event.target.value);
            if (!event.target.value) { setQuery(''); resetPage(); }
          }} /></label>
        <Button type="submit">Search</Button>
      </form>
      <div className={s.status} aria-live="polite">
        {busy && <span>Loading board…</span>}
        {error && <span className={s.warning}>{error}{snapshot && ' Showing the last loaded view.'}</span>}
        {snapshot && <>
          <Badge>{snapshot.state}</Badge>
          {snapshot.refresh_in_progress && <span>Source collection in progress.</span>}
          {snapshot.outcome && snapshot.outcome !== 'complete' && <span className={s.warning}>
            {explanation(snapshot.reason)} {snapshot.fetched_at && snapshot.state !== 'PARTIAL' && 'Showing the last complete board.'}
            {snapshot.next_retry_at && ' Retry eligible after ' + stamp(snapshot.next_retry_at) + '.'}
          </span>}
          {snapshot.state === 'PARTIAL' && <span>Only {count(snapshot.board_count)} rows could be verified.</span>}
          {snapshot.critically_stale ? <span className={s.warning}>Board is older than 48 hours.</span>
            : snapshot.state === 'STALE' && <span>Board is older than 12 hours.</span>}
        </>}
      </div>
      {snapshot && (snapshot.items.length > 0 ? <>
        <div className={s.tableRegion} tabIndex={0} role="region" aria-label="Trader rankings table">
          <table>
            <thead><tr><th scope="col">Rank</th><th scope="col">Trader</th>
              <th scope="col" className={s.numeric}>P&L <small>USDC</small></th>
              <th scope="col" className={s.numeric}>Volume <small>shares</small></th>
              <th scope="col" className={s.numeric}>Rank change</th></tr></thead>
            <tbody>{snapshot.items.map(row => <tr key={row.wallet}>
              <td className={s.rank}>{row.rank ?? '—'}</td>
              <td><button type="button" className={s.wallet} onClick={() => setWallet(row.wallet)}
                disabled={snapshot.state === 'PARTIAL' && row.rank !== null}
                aria-label={'Wallet details for ' + (row.name ?? row.wallet)}>
                <span className={s.monogram} aria-hidden="true">{(row.name ?? row.wallet.slice(2)).slice(0, 2).toUpperCase()}</span>
                <span><strong><bdi>{row.name ?? shortWallet(row.wallet)}</bdi></strong>
                  <small dir="ltr">{row.rank === null ? 'Outside this board · ' : ''}{shortWallet(row.wallet)}</small></span>
              </button></td>
              <td className={s.numeric}><bdi className={row.pnl?.startsWith('-') ? s.loss : row.pnl && row.pnl !== '0' ? s.gain : undefined}>{row.pnl ?? '—'}</bdi></td>
              <td className={s.numeric}><bdi>{row.volume ?? '—'}</bdi></td>
              <td className={s.numeric}>{row.rank_change === null ? '—' : row.rank_change > 0
                ? <span className={s.gain}>↑ {row.rank_change}</span> : row.rank_change < 0
                  ? <span className={s.loss}>↓ {Math.abs(row.rank_change)}</span> : '0'}</td>
            </tr>)}</tbody>
          </table>
        </div>
        <div className={s.pageNav}>
          <span>{count(snapshot.offset + 1)}–{count(snapshot.offset + snapshot.items.length)} of {count(snapshot.total)}
            {query ? ' matches' : ' collected rows'}</span>
          <div><Button variant="default" disabled={busy || snapshot.offset === 0} onClick={() => next(snapshot.offset - 50)}>Previous</Button>
            <Button variant="default" disabled={busy || snapshot.offset + 50 >= snapshot.total} onClick={() => next(snapshot.offset + 50)}>Next</Button></div>
        </div>
      </> : <p className={s.empty}>{query ? 'No matching wallets in the retained bank.' :
        snapshot.fetched_at && snapshot.board_count === 0 ? 'The provider returned an empty board.' : 'No board has been collected for this selection.'}</p>)}
      <footer className={s.note}>
        {snapshot?.has_more_at_source && <span>Collected top {count(snapshot.depth)}. More rows exist at the source. </span>}
        Rank change compares the previous capture of this board. Categories are available for the monthly view.
        {snapshot?.source_health_at && <span> Provider health report {stamp(snapshot.source_health_at)}.</span>}
      </footer>
    </section>
    <section className={s.benchmarks} id="leaderboard-coverage" tabIndex={-1} aria-label="Reference coverage">
      <h2>Reference coverage</h2><p>Wallets from each capture found in our independently collected bank.</p>
      {referenceError && <p role="status" className={s.warning}>Could not reload reference coverage.{references && ' Showing the last loaded comparisons.'}</p>}
      <div className={s.referenceGrid}>{references?.items.map(item => {
        const ratio = item.denominator && item.shared !== null && item.bank_count
          ? (100 * item.shared / item.denominator).toFixed(1) + '%' : '—';
        return <article className={s.reference} key={item.source}>
          <div className={s.referenceHeading}><h3>{item.source}</h3>
            <Badge>{!item.capture_id ? 'UNAVAILABLE' : !item.complete ? 'PARTIAL'
              : item.older_than_week ? 'STALE' : 'AVAILABLE'}</Badge></div>
          <strong>{ratio}</strong>
          <p>{item.denominator && item.bank_count && item.shared !== null
            ? count(item.shared) + ' of ' + count(item.denominator) + ' wallets'
            : item.capture_id ? 'No eligible comparison' : 'No reference capture'}</p>
          {item.captured_at && <small>Reference captured {stamp(item.captured_at)}</small>}
          {item.captured_at && item.bank_frozen_at && stamp(item.captured_at) !== stamp(item.bank_frozen_at)
            && <small>Bank as of {stamp(item.bank_frozen_at)}</small>}
          {item.capture_id !== null && <Button variant="subtle" onClick={() => setComparison(item)}>Compare {item.source}</Button>}
        </article>;
      })}</div>
    </section>
    <Modal opened={wallet !== null} onClose={() => setWallet(null)} title="Wallet detail" size="lg"
      returnFocus transitionProps={{ duration: 0 }} closeButtonProps={{ 'aria-label': 'Close wallet detail' }}>
      {wallet && <WalletDetail key={wallet + scope} wallet={wallet} scope={scope} onIdentityFailure={onIdentityFailure} />}
    </Modal>
    <Modal opened={comparison !== null} onClose={() => setComparison(null)}
      title={comparison ? comparison.source + ' coverage' : 'Reference coverage'} size="lg"
      returnFocus transitionProps={{ duration: 0 }} closeButtonProps={{ 'aria-label': 'Close reference coverage' }}>
      {comparison && <ComparisonDetail key={comparison.capture_id} capture={comparison} onIdentityFailure={onIdentityFailure} />}
    </Modal>
  </div>;
}

function WalletDetail({ wallet, scope, onIdentityFailure }: {
  wallet: string; scope: string; onIdentityFailure: () => void;
}) {
  const [detail, setDetail] = useState<LeaderboardWallet | null>(null);
  const [failed, setFailed] = useState(false);
  const [copy, setCopy] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    void read<LeaderboardWallet>('/leaderboard/wallet?' + scope + '&wallet=' + encodeURIComponent(wallet), 'LeaderboardWallet',
      AbortSignal.any([controller.signal, AbortSignal.timeout(4000)])).then(value => {
      if (!controller.signal.aborted) setDetail(value);
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      if (accessDenied(error)) onIdentityFailure();
      else setFailed(true);
    });
    return () => controller.abort();
  }, [wallet, scope, onIdentityFailure]);
  return <div className={s.detail}>
    <h3>{detail?.name ?? shortWallet(wallet)}</h3>
    <p><bdi dir="ltr">{wallet}</bdi></p>
    <div className={s.actions}>
      <Button variant="default" onClick={() => {
        void navigator.clipboard.writeText(wallet).then(() => setCopy('Address copied.'),
          () => setCopy('Copy unavailable. Select the address above.'));
      }}>Copy address</Button>
      <a href={'https://polymarket.com/profile/' + wallet} target="_blank" rel="noopener noreferrer">Polymarket profile ↗</a>
    </div>
    {copy && <p role="status">{copy}</p>}
    {!detail && <p role="status">{failed ? 'Wallet history is unavailable.' : 'Loading wallet evidence…'}</p>}
    {detail && <>
      <dl className={s.detailFacts}>
        <div><dt>First observed</dt><dd>{stamp(detail.first_seen)}</dd></div>
        <div><dt>Last observed</dt><dd>{stamp(detail.last_seen)}</dd></div>
      </dl>
      <h4>Recorded activity</h4>
      {detail.activity ? <>
        <p>{count(detail.activity.trades)} trade records · {count(detail.activity.markets)} markets
          {!detail.activity.complete && ' · Partial window'}</p>
        <p className={s.note}>{stamp(detail.activity.since)} to {stamp(detail.activity.through)}
          {detail.activity.latest && ' · Last trade ' + stamp(detail.activity.latest)}</p>
      </> : <p className={s.note}>Activity has not been collected for this wallet.</p>}
      <h4>Rank history on this board</h4>
      {detail.history.length > 0 ? <div className={s.tableRegion} role="region" tabIndex={0} aria-label="Rank history">
        <table><thead><tr><th scope="col">Observed</th><th scope="col">Rank</th><th scope="col">P&L (USDC)</th><th scope="col">Volume (shares)</th></tr></thead>
          <tbody>{detail.history.map((point, index) => <tr key={point.observed_at + index}><td>{stamp(point.observed_at)}</td>
            <td>{point.rank}</td><td><bdi>{point.pnl}</bdi></td><td><bdi>{point.volume}</bdi></td></tr>)}</tbody>
        </table>
      </div> : <p className={s.note}>No retained observations on this board.</p>}
    </>}
  </div>;
}

function ComparisonDetail({ capture, onIdentityFailure }: {
  capture: BenchmarkSummary; onIdentityFailure: () => void;
}) {
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<LeaderboardComparison | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    setPage(null); setFailed(false);
    void read<LeaderboardComparison>('/leaderboard/comparison?capture=' + capture.capture_id + '&offset=' + offset,
      'LeaderboardComparison', AbortSignal.any([controller.signal, AbortSignal.timeout(4000)])).then(value => {
      if (!controller.signal.aborted) setPage(value);
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      if (accessDenied(error)) onIdentityFailure();
      else setFailed(true);
    });
    return () => controller.abort();
  }, [capture.capture_id, offset, onIdentityFailure]);
  return <div className={s.detail}>
    <p>{capture.scope}</p><p className={s.note}>{capture.method}{capture.bank_frozen_at && ' · Bank as of ' + stamp(capture.bank_frozen_at)}</p>
    <p>Absent wallets were outside this bank capture. Rank and P&L agreement require comparable definitions.</p>
    {!page && <p role="status">{failed ? 'Comparison details are unavailable.' : 'Loading comparison…'}</p>}
    {page && <><div className={s.tableRegion} tabIndex={0} role="region" aria-label="Wallet overlap">
      <table><thead><tr><th scope="col">Wallet</th><th scope="col">Membership</th></tr></thead>
        <tbody>{page.items.map(item => <tr key={item.wallet}><td><bdi dir="ltr">{item.wallet}</bdi></td>
          <td>{item.shared ? 'Shared' : 'Outside captured bank'}</td></tr>)}</tbody></table></div>
      <div className={s.pageNav}><span>{count(page.total)} reference wallets</span>
        <div><Button variant="default" disabled={!offset} onClick={() => setOffset(offset - 50)}>Previous</Button>
          <Button variant="default" disabled={offset + 50 >= page.total} onClick={() => setOffset(offset + 50)}>Next</Button></div></div></>}
  </div>;
}
