import type { ReactNode } from 'react';
import type { Money } from '../contract.generated';
import { brand } from './brand';
import { statusTone } from './status';
import s from '../Console.module.css';
export function BrandLockup() {
  return (
    <>
      <img className={s.brandSymbol} src={brand.primary} width="56" height="56" alt="" />
      <span>
        <img className={s.wordmark} src={brand.wordmarkDark} width="112" height="30" alt="PolySia" />
        <small>CONSOLE</small>
      </span>
    </>
  );
}
export function Amount({ value }: { value: Money | null | undefined }) {
  return <span className={s.amount} title={value?.meaning}><bdi dir="ltr">{value?.value ?? 'UNKNOWN'}</bdi><span className={s.unit}>{value?.unit ?? 'UNKNOWN'}</span></span>;
}
export function Badge({ children, alert = false }: { children: ReactNode; alert?: boolean }) {
  const tone = alert ? 'bad' : typeof children === 'string' ? statusTone(children) : 'neutral';
  return <span className={`${s.badge} ${s[tone]}`}>{children}</span>;
}
