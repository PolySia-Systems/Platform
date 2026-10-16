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
    link.addEventListener("click", () => text("wallet-detail", `${row.wallet_id}: ${row.state}; last qualifying activity ${readable(row.last_qualifying_activity)}; ${row.execution_eligibility}; ${(row.exclusions || []).join(", ")}`));
    identity.append(link); tr.append(identity);
    [row.state, row.execution_eligibility].forEach(value => { const td = document.createElement("td"); td.textContent = readable(value); tr.append(td); });
    body.append(tr);
  });
  if (!rows.length) { const tr = document.createElement("tr"), td = document.createElement("td"); td.colSpan = 3; td.textContent = "No retained cohort is available."; tr.append(td); body.append(tr); }
}
async function load() {
  try { const commandResponse = await fetch("/api/commands"); if (commandResponse.ok) {
      const commands = await commandResponse.json(); revision = commands.revision;
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
    } }
  catch { text("receipt", "Command receipt service unavailable; inspect the protected recovery route."); }
  try {
    const response = await fetch("/api/report", {credentials:"same-origin"});
    if (!response.ok) throw new Error(`Publication unavailable (${response.status})`);
    publication = await response.json();
    const healthResponse = await fetch("/api/health");
    const health = await healthResponse.json();
    if (health.status === "FAILED") { const alert = document.getElementById("error"); alert.hidden = false; alert.textContent = "Report publisher failed; this is retained data. " + readable(health.next_action); }
    const report = publication.report || {}, analytical = report.analytical || {}, economics = analytical.report || {};
    const age = (Date.now() - Date.parse(publication.published_at)) / 1000;
    text("operation", age > 180 ? "STALE PUBLICATION" : publication.status || "UNKNOWN"); text("next", age > 180 ? "Inspect the report publisher; this is retained state." : publication.next_action);
    text("freshness", `Retained publication: ${readable(publication.published_at)} · live service health requires a current worker receipt`);
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
    const reasons = document.getElementById("reasons"); reasons.replaceChildren();
    [...(analytical.reasons || []), ...(report.limitations || []), ...(publication.alerts || [])].forEach(value => { const item = document.createElement("li"); item.textContent = value; reasons.append(item); });
    text("diagnostics", JSON.stringify(publication.diagnostics || {status:"UNKNOWN"}, null, 2));
    wallets();
  } catch (error) { const target = document.getElementById("error"); target.hidden = false; target.textContent = error.message; }
}
document.getElementById("wallet-filter").addEventListener("input", wallets);
document.querySelectorAll("button[data-action]").forEach(button => {
  button.disabled = document.querySelector('meta[name="role"]').content !== "operator";
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
      const response = await fetch("/api/commands", {method:"POST", credentials:"same-origin", headers:{"Content-Type":"application/json"}, body:JSON.stringify({action:button.dataset.action,parameters,expected_revision:revision,idempotency_key:crypto.randomUUID(),csrf:document.querySelector('meta[name="csrf"]').content})});
      const receipt = await response.json();
      text("receipt", response.ok ? `Command ${receipt.revision}: ${receipt.status}` : readable(receipt.reason));
      await load();
    } catch (error) { text("receipt", error.message || "Command result UNKNOWN; inspect durable receipts before retrying."); }
    finally { button.disabled = false; }
  });
});
load();
