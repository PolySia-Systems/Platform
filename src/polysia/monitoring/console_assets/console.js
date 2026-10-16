"use strict";
let publication = {}, revision = 0;
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
    link.addEventListener("click", () => text("wallet-detail", `${row.wallet_id}: ${row.state}; last qualifying activity ${readable(row.last_qualifying_activity)}; ${row.execution_eligibility}`));
    identity.append(link); tr.append(identity);
    [row.state, row.execution_eligibility].forEach(value => { const td = document.createElement("td"); td.textContent = readable(value); tr.append(td); });
    body.append(tr);
  });
  if (!rows.length) { const tr = document.createElement("tr"), td = document.createElement("td"); td.colSpan = 3; td.textContent = "No retained cohort is available."; tr.append(td); body.append(tr); }
}
async function load() {
  try {
    const response = await fetch("/api/report", {credentials:"same-origin"});
    if (!response.ok) throw new Error(`Publication unavailable (${response.status})`);
    publication = await response.json();
    const report = publication.report || {}, analytical = report.analytical || {}, economics = analytical.report || {};
    text("operation", publication.status || "UNKNOWN"); text("next", publication.next_action);
    text("freshness", `Retained publication: ${readable(publication.published_at)} · live service health requires a current worker receipt`);
    const measured = Number(economics.evaluated_observations || 0) > 0;
    text("control", measured ? economics.control?.net_pnl : "NO MEASURABLE RESULT");
    text("target", measured ? economics.target?.net_pnl : "NO MEASURABLE RESULT");
    text("delta", measured ? economics.control_target_net_delta : "UNKNOWN");
    text("sample", `${economics.total_observations || 0} observations · ${economics.unknown_observations || 0} UNKNOWN`);
    text("scope", report.scope || "No supported financial-session report yet.");
    text("digest", report.analytical_digest ? `Analytical SHA-256: ${report.analytical_digest}` : "No analytical digest yet.");
    const reasons = document.getElementById("reasons"); reasons.replaceChildren();
    [...(analytical.reasons || []), ...(report.limitations || []), ...(publication.alerts || [])].forEach(value => { const item = document.createElement("li"); item.textContent = value; reasons.append(item); });
    wallets();
    const commandResponse = await fetch("/api/commands");
    if (commandResponse.ok) revision = (await commandResponse.json()).revision;
  } catch (error) { const target = document.getElementById("error"); target.hidden = false; target.textContent = error.message; }
}
document.getElementById("wallet-filter").addEventListener("input", wallets);
document.querySelectorAll("button[data-action]").forEach(button => {
  button.disabled = document.querySelector('meta[name="role"]').content !== "operator";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      const response = await fetch("/api/commands", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:JSON.stringify({action:button.dataset.action,expected_revision:revision,idempotency_key:crypto.randomUUID(),csrf:document.querySelector('meta[name="csrf"]').content})});
      const receipt = await response.json();
      text("receipt", response.ok ? `Command ${receipt.revision}: ${receipt.status}` : readable(receipt.reason));
      await load();
    } catch { text("receipt", "Command result UNKNOWN; inspect durable receipts before retrying."); }
    finally { button.disabled = false; }
  });
});
load();
