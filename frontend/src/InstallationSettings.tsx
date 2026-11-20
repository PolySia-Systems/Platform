import { useEffect, useState } from 'react';
import type { InstallationSettings as Settings } from './contract.generated';
import { ApiError, read } from './client';
import { Timestamp } from './design/Primitives';
import s from './Console.module.css';

const command = 'sudo polysia-admin ';

export function InstallationSettings({ refresh }: { refresh: number }) {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [result, setResult] = useState<'pending' | 'ready' | 'failed'>('pending');

  useEffect(() => {
    const request = new AbortController();
    setResult('pending');
    const signal = AbortSignal.any([request.signal, AbortSignal.timeout(4000)]);
    void read<Settings>('/installation-settings', 'InstallationSettings', signal)
      .then(value => {
        if (request.signal.aborted) return;
        setSettings(value);
        setResult('ready');
      })
      .catch(error => {
        if (request.signal.aborted) return;
        if (error instanceof ApiError && error.status === 403) setSettings(null);
        setResult('failed');
      });
    return () => request.abort();
  }, [refresh]);

  const policy = settings?.update_automatic;
  return <section className={s.panel} aria-label="Installation settings">
    <h2>Manage this installation</h2>
    <p>Run these commands in the server's SSH terminal as its administrator.</p>
    {result === 'pending' && <p role="status">{settings
      ? 'Refreshing installation status. Showing the last successful read.'
      : 'Loading installation status…'}</p>}
    {result === 'failed' && <p role="status">{settings
      ? 'Could not read current installation status. Showing the last successful read. Use Refresh evidence to retry.'
      : 'Could not read installation status. Use Refresh evidence to retry.'}</p>}
    <dl>
      <dt>Accounts and passwords</dt>
      <dd><code>{command}configure --set-password owner</code></dd>
      <dt>Domain and access</dt>
      <dd>{settings?.profile ? <>{settings.profile} · </> : settings && 'Profile unknown · '}<code>{command}configure</code></dd>
      <dt>Polymarket wallet and API connection</dt>
      <dd>{settings && (settings.connection ?? 'No connection status recorded')}
        {settings?.authenticated && ' · API ' + settings.authenticated}
        {settings?.connection_checked_at && <> · <Timestamp value={settings.connection_checked_at} /></>}
        <div><code>{command}connection --connection-action set</code></div></dd>
      <dt>Backup and recovery</dt>
      <dd>{settings && (settings.backup_mode ?? 'Backup mode unknown')}
        {settings?.backup_status && ' · ' + settings.backup_status}
        <div><code>{command}backup</code></div></dd>
      <dt>Software updates</dt>
      <dd>{settings && <>{settings.release ?? 'Release unknown'} · {policy === true ? 'Automatic' : policy === false ? 'Manual' : 'Update policy unknown'}</>}
        {settings?.update_state && ' · Last check: ' + settings.update_state}
        {settings?.update_available && ' · Reported latest: ' + settings.update_available}
        <div><code>{command}updates</code></div></dd>
    </dl>
  </section>;
}
