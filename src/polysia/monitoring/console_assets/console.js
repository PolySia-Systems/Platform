"use strict";
let publication = {}, revision = 0, inFlight = null;
let refreshTimer = null, publisherFailure = null, reportFailure = null;
let renderedWallets = "", renderedReceipts = "";
let walletPage = 0;
const WALLET_PAGE_SIZE = 50;
const REFRESH_MS = 20000;
const IS_DEMO = document.querySelector('meta[name="dataset-mode"]').content === "demo";
// Keep English interface messages together; no translation framework is required.
const STATUS_TEXT = {UNCONFIGURED:"Observation is not configured", STOPPED:"Acquisition is stopped", OBSERVING:"Observation active", WAITING_CADENCE:"Waiting for the next scheduled observation", WAITING_RETRY:"Waiting before a bounded retry", WAITING_SOURCE_EVIDENCE:"Waiting for complete source evidence", DRAINING:"Closing existing inventory only", FAILED:"An operation failed", BLOCKED:"An operation needs attention", UNKNOWN:"Current state is unknown", "PUBLICATION UNAVAILABLE":"Publication unavailable", "STALE PUBLICATION":"Retained report is out of date", "STALE WORKER RECEIPT":"Worker status is out of date"};
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
  if (publisherAge == null && reportFailure) {
    operation = "PUBLICATION UNAVAILABLE"; next = "Inspect the publisher; no current publication is available.";
  } else if (publisherAge == null || publisherAge < -5 || publisherAge > 180) {
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
  if (!document.hidden) refreshTimer = setTimeout(() => { load(); }, REFRESH_MS);
}
async function load() {
  if (inFlight) return inFlight;
  document.getElementById("main").setAttribute("aria-busy", "true");
  inFlight = loadOnce().finally(() => {
    inFlight = null;
    // A completed refresh includes the next timer, not just rendered receipts.
    // Expose readiness only after the serialized read and scheduling finish.
    scheduleRefresh();
    document.getElementById("main").setAttribute("aria-busy", "false");
  });
  return inFlight;
}
const text = (id, value) => { document.getElementById(id).textContent = value ?? "UNKNOWN"; };
const readable = value => value == null ? "UNKNOWN" : String(value);
const rowsOrEmpty = value => Array.isArray(value) ? value : [];
const detailsText = value => value == null ? "UNKNOWN" : typeof value === "object" ? JSON.stringify(value) : String(value);
function tableRow(body, values) {
  const row = document.createElement("tr");
  values.forEach(value => { const cell = document.createElement("td"); cell.textContent = detailsText(value); row.append(cell); });
  body.append(row); return row;
}
function tableEmpty(body, columns, message) {
  const row = tableRow(body, [message]); row.firstChild.colSpan = columns;
}
function walletRecords() {
  const discovery = publication.diagnostic?.discovery?.candidates;
  return rowsOrEmpty(publication.selection?.records ?? discovery);
}
function walletRationale(row) {
  const ranking = typeof row.ranking_explanation === "string" ? row.ranking_explanation.trim() : "";
  return [ranking, ...rowsOrEmpty(row.reasons).map(detailsText)].filter(Boolean).join(" · ") || "UNKNOWN";
}
function walletExclusions(row) {
  return Array.isArray(row.exclusions) ? row.exclusions.map(detailsText).join(", ") || "None recorded" : "UNKNOWN";
}
function wallets() {
  const rows = walletRecords();
  const filter = document.getElementById("wallet-filter").value.trim().toLowerCase();
  const filtered = rows.filter(row => [row.wallet_id, row.state, row.execution_eligibility, row.eligibility, walletRationale(row), ...rowsOrEmpty(row.sources), ...rowsOrEmpty(row.exclusions)].map(detailsText).join(" ").toLowerCase().includes(filter));
  const pageCount = Math.max(1, Math.ceil(filtered.length / WALLET_PAGE_SIZE));
  walletPage = Math.min(Math.max(0, walletPage), pageCount - 1);
  const first = walletPage * WALLET_PAGE_SIZE;
  const body = document.getElementById("wallets"); body.replaceChildren();
  filtered.slice(first, first + WALLET_PAGE_SIZE).forEach(row => {
    const tr = document.createElement("tr");
    const identity = document.createElement("td"), link = document.createElement("button");
    link.className = "wallet-link"; link.textContent = readable(row.wallet_id);
    link.addEventListener("click", () => text("wallet-detail", `${readable(row.wallet_id)}: ${readable(row.state)} · Sources: ${rowsOrEmpty(row.sources).map(detailsText).join(", ") || "UNKNOWN"} · Last qualifying activity: ${readable(row.last_qualifying_activity)} · Execution eligibility: ${readable(row.execution_eligibility ?? row.eligibility)} · Selection rationale: ${walletRationale(row)} · Exclusions: ${walletExclusions(row)}. Discovery membership does not grant execution authority.`));
    identity.append(link); tr.append(identity);
    [rowsOrEmpty(row.sources).map(detailsText).join(", ") + " · " + readable(row.state), row.execution_eligibility ?? row.eligibility].forEach(value => { const td = document.createElement("td"); td.textContent = readable(value); tr.append(td); });
    body.append(tr);
  });
  if (!filtered.length) tableEmpty(body, 3, rows.length ? "No discovery records match this search." : "No retained discovery records are available.");
  text("wallet-page-status", `${filtered.length ? first + 1 : 0}–${Math.min(first + WALLET_PAGE_SIZE, filtered.length)} of ${filtered.length} matching / ${rows.length} available discovery records · Page ${walletPage + 1} of ${pageCount} · Active bounded monitors: ${readable(publication.selection?.monitored_count)}.`);
  document.getElementById("wallet-previous").disabled = walletPage === 0;
  document.getElementById("wallet-next").disabled = walletPage + 1 >= pageCount;
}
function definitions(id, values, labels) {
  const list = document.getElementById(id); list.replaceChildren();
  labels.forEach(([key, label]) => {
    const term = document.createElement("dt"), value = document.createElement("dd");
    term.textContent = label; value.textContent = detailsText(values?.[key]); list.append(term, value);
  });
}
function orderTimeline() {
  const orders = rowsOrEmpty(publication.financial_session?.orders);
  const filter = document.getElementById("order-filter").value.trim().toLowerCase();
  const matched = orders.filter(row => [row.intent_id, row.order_id, row.state, row.side, row.token].map(readable).join(" ").toLowerCase().includes(filter));
  const body = document.getElementById("order-timeline"); body.replaceChildren();
  matched.slice(0, 50).forEach(row => tableRow(body, [
    `${readable(row.order_id)} / ${readable(row.intent_id)}`, row.state,
    `${readable(row.side)} · ${readable(row.token)}`,
    `${readable(row.updated_at ?? row.created_at)} · ${readable(row.reason)}`,
  ]));
  if (!matched.length) tableEmpty(body, 4, orders.length ? "No orders match this search." : "No retained financial order evidence. Actual order state is UNKNOWN.");
  text("order-count", `${Math.min(50, matched.length)} shown / ${matched.length} matching orders. Search an exact identity to inspect other retained orders.`);
}
function sessionView() {
  const session = publication.financial_session;
  text("session-status", session ? `${readable(session.status)} · Recorded mode: ${readable(session.trading_mode)} · Financial cutoff: ${readable(session.as_of ?? session.observed_at ?? session.generated_at)}` : "No financial-session receipt. Status, authority, and exposure are UNKNOWN.");
  text("session-scope", `Scope: ${readable(session?.scope)} · Activation: ${readable(session?.activation)}`);
  definitions("session-authority", session?.remaining_authority, [["status", "Authority state"], ["expires_at", "Entry expiry (UTC)"], ["protective_until", "Protective authority expiry (UTC)"], ["attempts", "Attempts remaining"], ["turnover", "Turnover remaining"], ["requests", "Requests remaining"]]);
  definitions("session-exposure", session?.exposure, [["cash", "Cash"], ["open_exposure", "Open exposure"], ["reserved", "Reserved / unknown exposure"], ["positions", "Open positions"], ["reconciliation", "Reconciliation"]]);
  const incidents = document.getElementById("session-incidents"); incidents.replaceChildren();
  const incidentRows = rowsOrEmpty(session?.incidents);
  incidentRows.forEach(row => {
    const item = document.createElement("li");
    item.textContent = `${readable(row.reason)} · Scope: ${readable(row.scope)} · At: ${readable(row.at)} · Next: ${readable(row.next_action)}`; incidents.append(item);
  });
  if (!incidentRows.length) {
    const item = document.createElement("li");
    item.textContent = session && Array.isArray(session.incidents) ? "No incidents are recorded in this publication; current account health still requires fresh supervision." : "Incident evidence is UNKNOWN. Inspect the supervised financial-session receipt.";
    incidents.append(item);
  }
  const sources = rowsOrEmpty(session?.sources ?? publication.selection?.source_health);
  const sourceBody = document.getElementById("source-health"); sourceBody.replaceChildren();
  sources.forEach(row => tableRow(sourceBody, [row.source ?? row.source_id, `${readable(row.status)} · ${readable(row.phase)}`, `Age: ${readable(row.age_seconds)} seconds · Gaps: ${detailsText(row.gaps)}`, row.next_action]));
  if (!sources.length) tableEmpty(sourceBody, 4, "Source health is UNKNOWN. No retained source-health receipt is available.");
  const latency = session?.latency;
  text("session-timing", latency ? `Bottleneck: ${detailsText(latency.bottleneck)} · Measured spans: ${readable(latency.sample_count)} · Missing / censored: ${readable(latency.missing_count)} / ${readable(latency.censored_count)} · Clock quality: ${readable(latency.clock_quality)}` : "Timing evidence is UNKNOWN. No complete financial-session trace is published.");
  text("session-timing-detail", JSON.stringify(latency ?? {status:"UNKNOWN"}, null, 2));
  const economics = session?.economics;
  text("actual-economics-state", economics ? `${readable(economics.status)} · Valuation: ${readable(economics.valuation_method)} · As of: ${readable(economics.valued_at)}` : "No financial-session economics have been published. Actual results are UNKNOWN.");
  const economicsBody = document.getElementById("actual-economics"); economicsBody.replaceChildren();
  [["realized_pnl", "Realized before fees"], ["unrealized_pnl", "Unrealized"], ["fees", "Recorded fees"], ["net_pnl", "Net trading result"], ["drawdown", "Drawdown"], ["open_positions", "Open / censored positions"], ["provider_cost", "Provider cost (separate)"], ["infrastructure_cost", "Infrastructure cost (separate)"]].forEach(([key,label]) => tableRow(economicsBody, [label, economics?.[key]]));
  const value = economics?.source_value ?? session?.source_value ?? publication.selection?.source_value;
  text("source-value", typeof value === "string" ? value : value && typeof value === "object" ? `Shared coverage: ${readable(value.overlap_count)} · Exclusive coverage: ${detailsText(value.exclusive_coverage)} · ${readable(value.summary)}` : "Source value is UNKNOWN. Overlap and exclusive usable coverage have not been published.");
  text("source-value-detail", JSON.stringify({source_value:value ?? {status:"UNKNOWN"},funnel:session?.funnel ?? {status:"UNKNOWN"},source_removal_replay:"COUNTERFACTUAL ESTIMATE"}, null, 2));
  orderTimeline();
}
async function loadOnce() {
  await loadScopedControls(AbortSignal.timeout(10000));
  try { const commandResponse = IS_DEMO ? null : await fetch("/api/commands", {signal:AbortSignal.timeout(10000), cache:"no-store", credentials:"same-origin"});
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
    const response = await fetch(IS_DEMO ? "/api/demo" : "/api/report", {signal:AbortSignal.timeout(10000), cache:"no-store", credentials:"same-origin"});
    if (!response.ok) throw new Error(`Publication unavailable (${response.status})`);
    publication = await response.json();
    const recordedMode = publication.financial_session?.trading_mode;
    text("recorded-mode", IS_DEMO ? "Synthetic demo · no execution" : `Recorded mode: ${["DATA_ONLY", "PAPER", "LIVE"].includes(recordedMode) ? recordedMode : "UNKNOWN"} · publication is not permission`);
    reportFailure = null;
    try { if (!IS_DEMO) {
      const healthResponse = await fetch("/api/health", {signal:AbortSignal.timeout(10000), cache:"no-store", credentials:"same-origin"});
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
    text("source-sample", `Diagnostic snapshot: ${source.source_rows ?? "UNKNOWN"} sampled source rows · ${source.unique_wallets ?? "UNKNOWN"} qualifying identities · cutoff ${readable(source.cutoff)} · newest source age at fetch ${readable(source.seed_newest_age_seconds)} seconds. Separate available discovery pool: ${walletRecords().length} records.`);
    text("authority-window", `Authority expires ${readable(windowAuthority.expires_at)} · ${authority.requests_charged ?? "UNKNOWN"} / ${windowAuthority.maximum_requests ?? "UNKNOWN"} requests · ${authority.bytes_charged ?? "UNKNOWN"} / ${windowAuthority.maximum_bytes ?? "UNKNOWN"} bytes charged. STOP does not settle financial positions.`);
    const exclusionRows = [source.excluded || {}, analytical.excluded_execution_evidence || {}].flatMap(rows => Object.entries(rows).map(([reason,count]) => `${count} excluded: ${reason.replaceAll("_", " ")}`));
    const reasons = document.getElementById("reasons"); reasons.replaceChildren();
    [...(analytical.reasons || []), ...exclusionRows, ...(report.limitations || []), ...(publication.alerts || [])].forEach(value => { const item = document.createElement("li"); item.textContent = value; reasons.append(item); });
    text("diagnostics", JSON.stringify({source:publication.diagnostics || {status:"UNKNOWN"},recovery:publication.backup_health || {status:"UNKNOWN"}}, null, 2));
    sessionView(); operatorViews();

    const walletKey = JSON.stringify(walletRecords());
    if (walletKey !== renderedWallets) { wallets(); renderedWallets = walletKey; }
  } catch (error) {
    reportFailure = error.message;
    if (!Object.keys(publication).length) { sessionView(); wallets(); }
  }
  freshness();
  await loadSupervision(AbortSignal.timeout(4000));
}
document.getElementById("wallet-filter").addEventListener("input", () => { walletPage = 0; text("wallet-detail", ""); wallets(); });
document.getElementById("wallet-previous").addEventListener("click", () => { walletPage--; wallets(); });
document.getElementById("wallet-next").addEventListener("click", () => { walletPage++; wallets(); });
document.getElementById("order-filter").addEventListener("input", orderTimeline);
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
  if (!document.hidden) { load(); freshness(); }
});
setInterval(() => { if (!document.hidden) freshness(); }, 1000);
load();
if (IS_DEMO) {
  document.querySelector('a[href="/api/report"]').href = "/api/demo";
  const comparison = document.querySelector('a[href="/download/comparison.csv"]');
  comparison.removeAttribute("href"); comparison.setAttribute("aria-disabled", "true");
}

let scopedPreview = null;
function operatorViews() {
  const projection = publication.capabilities || {}, body = document.getElementById("capability-rows");
  body.replaceChildren();
  rowsOrEmpty(projection.capabilities).forEach(original => {
    const row = {...original, requirements: rowsOrEmpty(original.requirements).map(item => {
      const expiry = Date.parse(item.evidence?.expires_at || "");
      return item.state === "VERIFIED" && (!Number.isFinite(expiry) || expiry <= Date.now()) ? {...item, state:"EXPIRED"} : item;
    })};
    if (row.status !== "DISABLED" && row.requirements.some(item => rowsOrEmpty(row.required).includes(item.identity) && item.state !== "VERIFIED")) row.status = "BLOCKED";

    const blockers = rowsOrEmpty(row.requirements).filter(item => item.state !== "VERIFIED").map(item => `${item.identity}: ${item.state} · ${item.evidence?.reason || "Evidence missing"} · ${item.evidence?.next_action || "Inspect Setup requirements"}`);
    tableRow(body, [row.capability, row.status, blockers.join("; ") || "All required evidence is current"]);
  });
  if (!body.children.length) tableEmpty(body, 3, "Readiness UNKNOWN: no operation-specific evidence has been published.");
  const requirements = document.getElementById("setup-requirements"); requirements.replaceChildren();
  rowsOrEmpty(projection.catalog).forEach(item => {
    const line = document.createElement("p"); line.textContent = `${item.identity}: ${item.obtain}. Validate: ${item.validate}.`; requirements.append(line);
  });
  const account = publication.active_account || {};
  text("active-account", `Active account: ${readable(account.identity)} · Verification: ${readable(account.status)} · Observed: ${readable(account.observed_at)}. Revocation or identity change blocks old run authority.`);
  const effective = publication.copy_policy?.effective, staged = publication.copy_policy?.staged;
  text("policy-summary", effective ? `Effective policy ${effective.version} · ${effective.sizing} · Exit preset ${effective.exit_preset} · Re-entry ${effective.reentry ? "enabled within frozen scope" : "disabled"} · Digest ${readable(publication.copy_policy.digest)}. A stop attempts an eligible exit; it does not guarantee a price.` : "Effective policy UNKNOWN. No policy can grant financial authority.");
  text("policy-staged", staged ? `Staged policy ${staged.version}; current positions retain their original policy.` : "No future policy is staged. Existing positions retain their frozen policy.");
  text("shadow-lab-summary", rowsOrEmpty(publication.shadow_lab?.experiments).map(item => `${item.target}: ${item.phase} · Policy ${item.policy_digest}`).join("; ") || "No retained Lab experiments. Independent virtual returns are not one portfolio.");
  const backup = publication.backup || {};
  text("backup-readiness", `Financial recovery mode: ${readable(backup.mode)}. Last verified: ${readable(backup.last_verified_at)}. Independent restore: ${readable(backup.independent_restore)}. Missing or stale protection blocks financial readiness.`);
  const capacity = publication.capacity || {};
  text("capacity-summary", `Allocation: ${readable(capacity.allocation)} · Actual requests: ${readable(capacity.actual_requests)} · Measured bytes: ${readable(capacity.measured_response_bytes)} · Queue: ${readable(capacity.queue_depth)} / ${readable(capacity.queue_limit)} · Shared egress utilization: ${readable(capacity.external_shared_egress_utilization)}. Synthetic probes do not establish production capacity.`);
  const incidents = rowsOrEmpty(publication.incidents);
  text("incident-summary", incidents.length ? incidents.map(item => `${item.kind}: ${item.reason} · ${item.next_action} · Delivery ${item.delivery_state}`).join("; ") : "No actionable incident is published. No notification delivery is implied.");
}
async function loadScopedControls(signal) {
  if (IS_DEMO) return;
  try {
    const response = await fetch("/api/operations", {signal, cache:"no-store", credentials:"same-origin"});
    if (!response.ok) throw new Error("Scoped operations unavailable");
    const data = await response.json(), select = document.getElementById("scoped-target"), previous = select.value;
    select.replaceChildren();
    rowsOrEmpty(data.targets).forEach(target => { const option = document.createElement("option"); option.value = target; option.textContent = target; select.append(option); });
    if (rowsOrEmpty(data.targets).includes(previous)) select.value = previous;
    document.getElementById("scoped-preview-button").disabled = !select.value || document.querySelector('meta[name="role"]').content !== "operator";
    const list = document.getElementById("scoped-receipts"); list.replaceChildren();
    rowsOrEmpty(data.receipts).forEach(item => { const li = document.createElement("li"); li.textContent = `${item.target} revision ${item.revision}: ${item.status} · ${detailsText(item.result)}`; list.append(li); });
  } catch { document.getElementById("scoped-preview-button").disabled = true; text("scoped-preview", "Scoped operation service unavailable; retained financial evidence remains visible."); }
}
async function scopedRequest(path, body) {
  const csrf = document.querySelector('meta[name="csrf"]').content;
  const response = await fetch(path, {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:JSON.stringify({...body, csrf}), signal:AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error(`Operation blocked (${response.status}); refresh and preview again.`);
  return response.json();
}
document.getElementById("scoped-preview-button").addEventListener("click", async () => {
  const operation = document.getElementById("scoped-operation").value, target = document.getElementById("scoped-target").value, argument = document.getElementById("scoped-argument").value.trim();
  const key = {"shadow.clone":"source", "shadow.compare":"other", "shadow.create":"policy_digest", "policy.stage":"policy_digest"}[operation];
  try { scopedPreview = await scopedRequest("/api/operations/preview", {operation, target, arguments:key ? {[key]:argument} : {}});
    text("scoped-preview", `Preview ${scopedPreview.operation} on ${scopedPreview.target} at revision ${scopedPreview.expected_revision}. Expires ${scopedPreview.expires_at}. Effect: not requested.`); document.getElementById("scoped-apply-button").disabled = false;
  } catch (error) { scopedPreview = null; text("scoped-preview", error.message); }
});
["scoped-target", "scoped-operation", "scoped-argument"].forEach(id => document.getElementById(id).addEventListener("input", () => { scopedPreview = null; document.getElementById("scoped-apply-button").disabled = true; }));
document.getElementById("scoped-apply-button").addEventListener("click", async () => {
  if (!scopedPreview) return;
  document.getElementById("scoped-apply-button").disabled = true;
  try { const receipt = await scopedRequest("/api/operations/apply", {preview_id:scopedPreview.preview_id, expected_revision:scopedPreview.expected_revision, idempotency_key:crypto.randomUUID()}); text("scoped-preview", `Requested revision ${receipt.revision}: ${receipt.status}. Effect ${receipt.effect || "inspect execution receipt"}.`); scopedPreview = null; await load(); }
  catch (error) { text("scoped-preview", error.message); scopedPreview = null; }
});

async function loadSupervision(signal) {
  if (IS_DEMO) return;
  try {
    const response = await fetch("/api/supervision", {signal, cache:"no-store", credentials:"same-origin"});
    if (!response.ok) throw new Error("Independent supervision UNKNOWN");
    const value = await response.json();
    const current = Date.parse(value.expires_at) > Date.now()
      && value.scope === publication.financial_session?.identity?.run;
    text("independent-supervision", `Independent supervision: ${current ? value.status : "EXPIRED"}. ${readable(value.reason)}. ${readable(value.next_action)}. This observation takes precedence over a retained worker view.`);
    if (publication.version === "operational-session-publication/v1" && (!current || value.status !== "SUPERVISED")) text("session-status", `Financial actions BLOCKED by independent supervision: ${current ? value.status : "EXPIRED"}. Retained order and economics evidence remains below.`);
  } catch { text("independent-supervision", "Independent supervision UNKNOWN; financial readiness is not established by a retained publication.");
    if (publication.version === "operational-session-publication/v1") text("session-status", "Financial readiness BLOCKED: independent supervision UNKNOWN. Retained financial evidence follows.");
  }
}
