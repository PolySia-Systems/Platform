import { useEffect, useState } from 'react';
import type { InstallationSettings as Settings } from './contract.generated';
import { read } from './client';
import s from './Console.module.css';

const command = 'sudo polysia-admin ';

export function InstallationSettings() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const signal = new AbortController();
    void read<Settings>('/installation-settings', 'InstallationSettings', signal.signal)
      .then(setSettings).catch(() => { if (!signal.signal.aborted) setFailed(true); });
    return () => signal.abort();
  }, []);
  return <section className={s.panel} aria-label="Installation settings">
    <h2>Manage this installation</h2>
    <p>Run these commands in the server’s SSH terminal as its administrator.</p>
    {failed && <p role="status">Could not read installation status. Refresh to retry.</p>}
    <dl>
      <dt>Accounts and passwords</dt>
      <dd><code>{command}configure --set-password owner</code></dd>
      <dt>Domain and access</dt>
      <dd>{settings?.profile ?? 'Profile unavailable'} · <code>{command}configure</code></dd>
      <dt>Polymarket wallet and API connection</dt>
      <dd>{settings?.connection ?? 'No connection receipt'}
        {settings?.authenticated && ' · API ' + settings.authenticated}
        {settings?.connection_checked_at && ' · ' + new Date(settings.connection_checked_at).toLocaleString()}
        <br /><code>{command}connection --connection-action set</code></dd>
      <dt>Backup and recovery</dt>
      <dd>{settings?.backup_mode ?? 'Backup mode unavailable'}
        {settings?.backup_status && ' · ' + settings.backup_status}
        <br /><code>{command}backup</code></dd>
      <dt>Software updates</dt>
      <dd>{settings?.release ?? 'Release unavailable'} · {settings?.update_automatic ? 'Automatic' : 'Manual'}
        {settings?.update_available && ' · Latest ' + settings.update_available}
        <br /><code>{command}updates</code></dd>
    </dl>
  </section>;
}
