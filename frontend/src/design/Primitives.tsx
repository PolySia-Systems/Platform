import type { ReactNode } from 'react';
import type { Money } from '../contract.generated';
import { brand } from './brand';
import { m } from '../messages';
import { statusTone } from './status';
import s from '../Console.module.css';
export function BrandLockup() {
  return (
    <>
      <img className={s.brandSymbol} src={brand.symbolDark} width="56" height="56" alt="" />
      <span>
        <img className={s.wordmark} src={brand.wordmarkDark} width="112" height="30" alt="PolySia" />
        <small>CONSOLE</small>
      </span>
    </>
  );
}
export function stamp(value: string | null | undefined, locale = 'en-GB') {
  const timestamp = value ? Date.parse(value) : NaN;
  if (!Number.isFinite(timestamp)) return m.unknown;
  return new Intl.DateTimeFormat(locale, {
    dateStyle: 'medium', timeStyle: 'medium', timeZone: 'UTC',
  }).format(timestamp) + ' UTC';
}
export function Timestamp({ value, locale }: { value: string | null | undefined; locale?: string }) {
  return <bdi dir="ltr">{stamp(value, locale)}</bdi>;
}
export function Amount({ value }: { value: Money | null | undefined }) {
  return <span className={s.amount} title={value?.meaning}><bdi dir="ltr">{value?.value ?? 'UNKNOWN'}</bdi><span className={s.unit}>{value?.unit ?? 'UNKNOWN'}</span></span>;
}
export function Badge({ children, alert = false }: { children: ReactNode; alert?: boolean }) {
  const tone = alert ? 'bad' : typeof children === 'string' ? statusTone(children) : 'neutral';
  return <span className={`${s.badge} ${s[tone]}`}>{children}</span>;
}
