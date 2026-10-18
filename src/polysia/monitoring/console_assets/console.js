"use strict";
let publication = {}, revision = 0, inFlight = null;
let refreshTimer = null, publisherFailure = null, reportFailure = null;
let renderedWallets = "", renderedReceipts = "";
const REFRESH_MS = 20000;
const IS_DEMO = document.querySelector('meta[name="dataset-mode"]').content === "demo";
// Keep English interface messages together; no translation framework is required.
const STATUS_TEXT = {UNCONFIGURED:"Observation is not configured", STOPPED:"Acquisition is stopped", OBSERVING:"Observation active", WAITING_CADENCE:"Waiting for the next scheduled observation", WAITING_RETRY:"Waiting before a bounded retry", WAITING_SOURCE_EVIDENCE:"Waiting for complete source evidence", DRAINING:"Closing existing inventory only", FAILED:"An operation failed", BLOCKED:"An operation needs attention", UNKNOWN:"Current state is unknown", "STALE PUBLICATION":"Retained report is out of date", "STALE WORKER RECEIPT":"Worker status is out of date"};
function ageSeconds(value) {
  const stamp = Date.parse(value);
  return Number.isFinite(stamp) ? (Date.now() - stamp) / 1000 : null;
}
function freshness() {
  if (IS_DEMO) {
    text("operation", "Offline demonstration"); text("next", publication.next_action);
    text("freshness", "Fictional example only. No financial result or acquisition authority.");
    return;
  }
  const publisherAge = ageSeconds(publication.published_at);
  const workerAge = ageSeconds(publication.last_attempt);
  let operation = publication.status || "UNKNOWN", next = publication.next_action;
  if (publisherAge == null || publisherAge < -5 || publisherAge > 180) {
    operation = "STALE PUBLICATION"; next = "Inspect the publisher; this is retained state.";
  } else if (workerAge == null || workerAge < -5 || workerAge > 180) {
    operation = "STALE WORKER RECEIPT"; next = "Inspect the worker; publication is retained data.";
  }
  text("operation", STATUS_TEXT[operation] || operation.replaceAll("_", " ")); text("next", next);
  const age = value => value == null ? "UNKNOWN" : `${Math.max(0, Math.floor(value))} seconds`;
  text("freshness", `Worker receipt age: ${age(workerAge)} · Publisher age: ${age(publisherAge)} · Financial cutoff: ${readable(publication.report?.analytical?.source_poll_cutoff)}`);
  const alert = document.getElementById("error");
  alert.hidden = !publisherFailure && !reportFailure;
  alert.textContent = reportFailure || publisherFailure || "";
}
function scheduleRefresh() {
  clearTimeout(refreshTimer);
  if (!document.hidden) refreshTimer = setTimeout(async () => {
    await load(); scheduleRefresh();
  }, REFRESH_MS);
}
async function load() {
  if (inFlight) return inFlight;
  inFlight = loadOnce().finally(() => { inFlight = null; });
  return inFlight;
}
const text = (id, value) => { document.getElementById(id).textContent = value ?? "UNKNOWN"; };
const readable = value => value == null ? "UNKNOWN" : String(value);
function wallets() {
  const rows = publication.diagnostic?.discovery?.candidates || [];
  const filter = document.getElementById("wallet-filter").value.trim().toLowerCase();
  const body = document.getElementById("wallets"); body.replaceChildren();
  rows.filter(row => row.wallet_id.toLowerCase().includes(filter)).forEach(row => {
    const tr = document.createElement("tr");
    const identity = document.createElement("td"), link = document.createElement("button");
    link.className = "wallet-link"; link.textContent = row.wallet_id;
    link.addEventListener("click", () => text("wallet-detail", `${row.wallet_id}: ${row.state}; last qualifying activity ${readable(row.last_qualifying_activity)}; ${row.execution_eligibility}; ${(row.exclusions || []).join(", ")}`));
    identity.append(link); tr.append(identity);
    [row.state, row.execution_eligibility].forEach(value => { const td = document.createElement("td"); td.textContent = readable(value); tr.append(td); });
    body.append(tr);
  });
  if (!rows.length) { const tr = document.createElement("tr"), td = document.createElement("td"); td.colSpan = 3; td.textContent = "No retained cohort is available."; tr.append(td); body.append(tr); }
}
async function loadOnce() {
  const signal = AbortSignal.timeout(10000);
  try { const commandResponse = IS_DEMO ? null : await fetch("/api/commands", {signal, cache:"no-store", credentials:"same-origin"});
    if (IS_DEMO) { text("receipt", "Demo is read-only. Commands use retained evidence only."); }
    else {
    if (!commandResponse.ok) throw new Error("Command receipt service unavailable.");
    if (commandResponse.ok) {
      const commands = await commandResponse.json(); revision = commands.revision;
      if (document.getElementById("receipt").textContent.startsWith("Command receipt service unavailable")) text("receipt", "");
      const receiptKey = JSON.stringify(commands.receipts || []);
      if (receiptKey !== renderedReceipts) {
      renderedReceipts = receiptKey;
      const list = document.getElementById("receipts"); list.replaceChildren();
      (commands.receipts || []).forEach(row => {
        const li = document.createElement("li");
        li.textContent = `Command ${row.revision}: ${row.action} · ${row.status} ${row.result?.reason || ""} ${row.result?.detail || ""}`;
        if (/^\/reports\/[a-f0-9]{64}\.json$/.test(row.result?.download || "")) {
          const link = document.createElement("a"); link.href = row.result.download;
          link.textContent = " Download retained report"; li.append(link);
        }
        list.append(li);
      });
      }
    } } }
  catch { text("receipt", "Command receipt service unavailable; inspect the protected recovery route."); }
  try {
    const response = await fetch(IS_DEMO ? "/api/demo" : "/api/report", {signal, cache:"no-store", credentials:"same-origin"});
    if (!response.ok) throw new Error(`Publication unavailable (${response.status})`);
    publication = await response.json();
    reportFailure = null;
    try { if (!IS_DEMO) {
      const healthResponse = await fetch("/api/health", {signal, cache:"no-store", credentials:"same-origin"});
      if (!healthResponse.ok) throw new Error("Publisher health unavailable; inspect retained receipts.");
      const health = await healthResponse.json();
      publisherFailure = health.status === "FAILED"
        ? "Report publisher failed; this is retained data. " + readable(health.next_action)
        : health.status === "UNKNOWN" ? "Publisher health is UNKNOWN; inspect retained receipts." : null;
    } } catch (error) { publisherFailure = error.message; }
    const installed = publication.installation || {};
    const observing = publication.status === "OBSERVING";
    text("setup-state", IS_DEMO ? "Offline demo · all controls are disabled" : `Installed release: ${installed.version || publication.package_version || "UNKNOWN"} · Browser access: ${installed.profile || "protected"} · ${observing ? "Observation active" : "Observation is not authorized or is stopped"}`);
    const protection = publication.backup_health?.backup;
    text("protection-state", IS_DEMO ? "Demo has no backup or recovery claim." : protection?.status === "UNPROTECTED" ? "UNPROTECTED — no backup destination is selected. Choose and verify one through the administrative entry." : `Backup: ${readable(protection?.status)} · Last check: ${readable(protection?.checked_at || protection?.created_at)} · Independent restore: ${readable(publication.backup_health?.restore?.status)}`);
    text("installation-details", JSON.stringify({installed,worker_release:publication.release_commit,publisher_release:publication.publisher_release_commit,status:publication.status}, null, 2));
    const report = publication.report || {}, analytical = report.analytical || {}, economics = analytical.report || {};
    freshness();
    const measured = Number(economics.evaluated_observations || 0) > 0;
    const window = analytical.selected_window;
    text("control", measured ? window?.control?.net_result ?? economics.control?.net_pnl : "NO MEASURABLE RESULT");
    text("target", measured ? window?.target?.net_result ?? economics.target?.net_pnl : "NO MEASURABLE RESULT");
    text("delta", measured ? window?.target_minus_control ?? economics.control_target_net_delta : "UNKNOWN");
    text("sample", `${economics.total_observations || 0} observations · ${economics.unknown_observations || 0} UNKNOWN`);
    text("scope", (report.scope || "No supported financial-session report yet.") + (publication.dataset_role ? " · Data role: " + publication.dataset_role : ""));
    text("digest", report.analytical_digest ? `Analytical SHA-256: ${report.analytical_digest}` : "No analytical digest yet.");
    const state = window || analytical.financial_state || {}, table = document.getElementById("financial-state"); table.replaceChildren();
    [["opening_cash","Opening cash"],["closing_cash","Closing cash"],["realized_before_fees","Realized before recorded fees"],["unrealized_after_hypothetical_exit_fees","Unrealized / liquidation result"],["recorded_fees","Recorded fees"],["hypothetical_exit_fees","Hypothetical exit fees"],["fill_embedded_slippage","Fill-embedded slippage"],["net_result","Net result"],["operating_costs","Operating costs"]].forEach(([key,label]) => {
      const tr = document.createElement("tr"); [label,readable(state.control?.[key]),readable(state.target?.[key])].forEach(value => { const td = document.createElement("td"); td.textContent = value; tr.append(td); }); table.append(tr);
    });
    text("positions", JSON.stringify({control:state.control?.closing_positions || [],target:state.target?.closing_positions || []},null,2));
    const source = publication.diagnostic?.discovery || {}, authority = publication.authority || {}, windowAuthority = publication.authority_window || {};
    text("source-sample", `${source.source_rows ?? "UNKNOWN"} sampled source rows · ${source.unique_wallets ?? "UNKNOWN"} qualifying identities · cutoff ${readable(source.cutoff)} · newest source age at fetch ${readable(source.seed_newest_age_seconds)} seconds`);
    text("authority-window", `Authority expires ${readable(windowAuthority.expires_at)} · ${authority.requests_charged ?? "UNKNOWN"} / ${windowAuthority.maximum_requests ?? "UNKNOWN"} requests · ${authority.bytes_charged ?? "UNKNOWN"} / ${windowAuthority.maximum_bytes ?? "UNKNOWN"} bytes charged. STOP does not settle financial positions.`);
    const exclusionRows = [source.excluded || {}, analytical.excluded_execution_evidence || {}].flatMap(rows => Object.entries(rows).map(([reason,count]) => `${count} excluded: ${reason.replaceAll("_", " ")}`));
    const reasons = document.getElementById("reasons"); reasons.replaceChildren();
    [...(analytical.reasons || []), ...exclusionRows, ...(report.limitations || []), ...(publication.alerts || [])].forEach(value => { const item = document.createElement("li"); item.textContent = value; reasons.append(item); });
    text("diagnostics", JSON.stringify({source:publication.diagnostics || {status:"UNKNOWN"},recovery:publication.backup_health || {status:"UNKNOWN"}}, null, 2));
    const walletKey = JSON.stringify(publication.diagnostic?.discovery?.candidates || []);
    if (walletKey !== renderedWallets) { wallets(); renderedWallets = walletKey; }
  } catch (error) { reportFailure = error.message; }
  freshness();
}
document.getElementById("wallet-filter").addEventListener("input", wallets);
document.querySelectorAll("button[data-action]").forEach(button => {
  button.disabled = IS_DEMO || document.querySelector('meta[name="role"]').content !== "operator";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const parameters = {};
      if (button.dataset.action === "export") {
        const start = document.getElementById("report-start").value;
        const end = document.getElementById("report-end").value;
        if (Boolean(start) !== Boolean(end)) throw new Error("Enter both UTC boundaries.");
        if (start && end) { parameters.start = new Date(start + "Z").toISOString(); parameters.end = new Date(end + "Z").toISOString(); }
      }
      const response = await fetch("/api/commands", {method:"POST", signal:AbortSignal.timeout(10000), credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:JSON.stringify({action:button.dataset.action,parameters,expected_revision:revision,idempotency_key:crypto.randomUUID(),csrf:document.querySelector('meta[name="csrf"]').content})});
      const receipt = await response.json();
      text("receipt", response.ok ? `Command ${receipt.revision}: ${receipt.status}` : readable(receipt.reason));
      await load();
    } catch (error) { text("receipt", error.message || "Command result UNKNOWN; inspect durable receipts before retrying."); }
    finally { button.disabled = false; }
  });
});
document.addEventListener("visibilitychange", () => {
  clearTimeout(refreshTimer);
  if (!document.hidden) { load().finally(scheduleRefresh); freshness(); }
});
setInterval(() => { if (!document.hidden) freshness(); }, 1000);
load().finally(scheduleRefresh);
if (IS_DEMO) {
  document.querySelector('a[href="/api/report"]').href = "/api/demo";
  const comparison = document.querySelector('a[href="/download/comparison.csv"]');
  comparison.removeAttribute("href"); comparison.setAttribute("aria-disabled", "true");
}
