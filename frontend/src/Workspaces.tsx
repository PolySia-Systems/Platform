import { useEffect, useState } from 'react';
import type { Workspace } from './contract.generated';
import { ApiError, read } from './client';
import { m } from './messages';
import s from './Console.module.css';

export const valueDirection = (value: string | null) => value !== null && /^[A-Za-z0-9_.:/+ -]+$/.test(value) ? 'ltr' : 'auto';

export function EvidenceWorkspace({ panel, generation, identity, clock, onIdentityFailure }: {
  panel: 'operate' | 'evaluate' | 'system'; generation: string | null; identity: string;
  clock: number; onIdentityFailure: () => void;
}) {
  const [value, setValue] = useState<Workspace | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    setValue(null); setError('');
    if (!identity) return () => controller.abort();
    void read<Workspace>('/workspace?panel=' + panel, 'Workspace',
      AbortSignal.any([controller.signal, AbortSignal.timeout(4000)])).then(result => {
      if (!controller.signal.aborted) setValue(result);
    }).catch(reason => {
      if (controller.signal.aborted) return;
      if (reason instanceof ApiError && reason.status === 403) onIdentityFailure();
      else setError(m.missing);
    });
    return () => controller.abort();
  }, [panel, generation, identity, onIdentityFailure]);
  return <div role="group" aria-label={m.evidenceWorkspace}>
    {error && <p role="alert">{error}</p>}
    {!value && !error && <p role="status">{m.loading}</p>}
    {value?.sections.map(section => {
      const expired = section.validity.valid_until !== null && clock >= Date.parse(section.validity.valid_until);
      const state = expired ? m.stale : section.validity.state;
      return <section className={s.panel} key={section.title} aria-label={section.title}>
        <div className={s.panelHeading}><h2>{section.title}</h2><span className={`${s.badge} ${state !== 'AVAILABLE' ? s.bad : ''}`}>{state}</span></div>
        <p className={s.muted}>{m.observedAt}: <bdi dir="ltr">{section.validity.observed_at ?? m.unknown}</bdi>
          {' · '}{m.validUntil}: <bdi dir="ltr">{section.validity.valid_until ?? m.unknown}</bdi></p>
        <dl className={s.facts}>{section.facts.map(fact => <div key={fact.label}>
          <dt>{fact.label}</dt><dd><bdi dir={valueDirection(fact.value)}>{fact.value ?? m.unknown}</bdi></dd></div>)}</dl>
        {section.tables.map(table => <div key={table.title}>
          <h3>{table.title} <span className={`${s.badge} ${table.state !== 'AVAILABLE' ? s.bad : ''}`}>{table.state}</span></h3>
          <div className={s.tableRegion} tabIndex={0} role="region" aria-label={table.title}>
            <table><thead><tr>{table.columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
              <tbody>{table.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}><bdi dir={valueDirection(cell)}>{cell ?? m.unknown}</bdi></td>)}</tr>)}</tbody></table>
          </div>
          <p className={s.muted}>{table.rows.length} / {table.total ?? m.unknown} {m.observations}{(table.total ?? 0) > table.rows.length ? ' · ' + m.boundedView : ''}</p>
          {table.total === 0 && <p>{m.noPublishedRows}</p>}
        </div>)}
        <p className={s.muted}>{section.guidance}</p>
      </section>;
    })}
  </div>;
}
