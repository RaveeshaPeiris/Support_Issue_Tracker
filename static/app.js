const $ = (id) => document.getElementById(id);
const state = { editingId: null, deletingId: null };

const esc = (s) => String(s).replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (iso) => new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove("show"), 2200);
}

async function api(url, opts = {}) {
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = res.status === 204 ? null : await res.json();
  if (!res.ok) throw { status: res.status, errors: (data && data.errors) || { _: "Something went wrong." } };
  return data;
}

// ---------- list ----------
async function load() {
  const p = new URLSearchParams();
  if ($("search").value.trim()) p.set("search", $("search").value.trim());
  if ($("fEngineer").value.trim()) p.set("engineer", $("fEngineer").value.trim());
  if ($("fPriority").value) p.set("priority", $("fPriority").value);
  if ($("fStatus").value) p.set("status", $("fStatus").value);
  try {
    render(await api("/api/issues?" + p));
  } catch (e) {
    toast("Could not load issues. Check that the server is running.");
  }
}

function render(issues) {
  const urgent = issues.filter((i) => i.needs_attention).length;
  $("summary").textContent =
    `${issues.length} issue${issues.length === 1 ? "" : "s"} shown` +
    (urgent ? `, ${urgent} need${urgent === 1 ? "s" : ""} attention` : "");
  $("empty").hidden = issues.length > 0;
  $("rows").innerHTML = issues.map((i) => `
    <tr class="${i.needs_attention ? "attention" : ""}">
      <td class="id">${esc(i.issue_id)}</td>
      <td>${esc(i.client_name)}</td>
      <td><div class="title">${esc(i.title)}</div>
          ${i.description ? `<div class="desc">${esc(i.description)}</div>` : ""}
          ${i.needs_attention ? `<span class="flag">Overdue: high priority, open over 24h</span>` : ""}</td>
      <td>${i.engineer ? esc(i.engineer) : "Unassigned"}</td>
      <td class="pri ${i.priority}">${i.priority}</td>
      <td><select data-status="${i.id}" aria-label="Status for ${esc(i.issue_id)}">
        ${["Open", "In Progress", "Resolved"].map((s) =>
          `<option${s === i.status ? " selected" : ""}>${s}</option>`).join("")}
      </select></td>
      <td>${fmt(i.reported_at)}</td>
      <td><div class="rowact">
        <button class="btn small" data-edit="${i.id}">Edit</button>
        <button class="btn small" data-del="${i.id}" data-label="${esc(i.issue_id + " " + i.title)}">Delete</button>
      </div></td>
    </tr>`).join("");
  window.__issues = Object.fromEntries(issues.map((i) => [i.id, i]));
}

// ---------- add / edit ----------
function clearErrors() { document.querySelectorAll(".err").forEach((e) => (e.textContent = "")); }

function openForm(issue) {
  clearErrors();
  const f = $("issueForm");
  state.editingId = issue ? issue.id : null;
  $("formTitle").textContent = issue ? `Edit ${issue.issue_id}` : "New issue";
  f.client_name.value = issue ? issue.client_name : "";
  f.title.value = issue ? issue.title : "";
  f.description.value = issue ? issue.description : "";
  f.engineer.value = issue ? issue.engineer : "";
  f.priority.value = issue ? issue.priority : "Medium";
  f.status.value = issue ? issue.status : "Open";
  $("reportedInfo").textContent = issue ? `Reported ${fmt(issue.reported_at)}` : "The report time is recorded when you save.";
  $("formDlg").showModal();
  f.client_name.focus();
}

$("issueForm").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  clearErrors();
  const f = ev.target;
  const body = Object.fromEntries(
    ["client_name", "title", "description", "engineer", "priority", "status"].map((k) => [k, f[k].value]));
  try {
    if (state.editingId) {
      await api(`/api/issues/${state.editingId}`, { method: "PUT", body });
      toast("Issue updated");
    } else {
      await api("/api/issues", { method: "POST", body });
      toast("Issue added");
    }
    $("formDlg").close();
    load();
  } catch (e) {
    for (const [k, v] of Object.entries(e.errors || {})) {
      const el = document.querySelector(`.err[data-for="${k}"]`);
      if (el) el.textContent = v; else toast(v);
    }
  }
});

// ---------- table actions (event delegation) ----------
$("rows").addEventListener("click", (ev) => {
  const edit = ev.target.closest("[data-edit]");
  const del = ev.target.closest("[data-del]");
  if (edit) openForm(window.__issues[edit.dataset.edit]);
  if (del) {
    state.deletingId = del.dataset.del;
    $("delText").textContent = `${del.dataset.label} will be removed permanently.`;
    $("delDlg").showModal();
  }
});

$("rows").addEventListener("change", async (ev) => {
  const sel = ev.target.closest("[data-status]");
  if (!sel) return;
  try {
    await api(`/api/issues/${sel.dataset.status}`, { method: "PATCH", body: { status: sel.value } });
    toast(`Status changed to ${sel.value}`);
  } catch (e) {
    const message = e.errors && (e.errors.engineer || e.errors.status);
    toast(message || "Could not change status");
  }
  load();
});

$("delConfirm").addEventListener("click", async () => {
  try {
    await api(`/api/issues/${state.deletingId}`, { method: "DELETE" });
    toast("Issue deleted");
  } catch (e) {
    toast("Could not delete the issue");
  }
  $("delDlg").close();
  load();
});

// ---------- wiring ----------
$("addBtn").onclick = () => openForm(null);
$("cancelBtn").onclick = () => $("formDlg").close();
$("delCancel").onclick = () => $("delDlg").close();
$("clearBtn").onclick = () => {
  $("search").value = ""; $("fEngineer").value = ""; $("fPriority").value = ""; $("fStatus").value = ""; load();
};
let debounce;
$("search").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(load, 250); });
$("fEngineer").addEventListener("input", () => { clearTimeout(debounce); debounce = setTimeout(load, 250); });
$("fPriority").addEventListener("change", load);
$("fStatus").addEventListener("change", load);

load();
setInterval(load, 60000); // refresh so the 24h highlight stays current
