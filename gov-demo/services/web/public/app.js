import { api, token } from "./api.js";
import { h, field } from "./dom.js";
import { syncWidget } from "./widget.js";

const STEPS = ["Payment type", "Your details", "Eligibility", "Documents", "Review and submit"];
const root = document.getElementById("app");
const state = {
  get claimId() { return sessionStorage.getItem("claimId"); },
  set claimId(v) { sessionStorage.setItem("claimId", v); },
};

// Custom action names make funnels easy to define when RUM is present: enter the action, then leave it.
function stepAction(name) {
  try {
    const id = window.dtrum?.enterAction?.(name, "custom");
    if (id !== undefined && id !== null) window.dtrum.leaveAction(id);
  } catch (_) { /* RUM optional */ }
}

function stepper(current) {
  return h("ol", { class: "steps" }, STEPS.map((s, i) =>
    h("li", { class: i + 1 < current ? "done" : i + 1 === current ? "current" : "" }, `${i + 1}. ${s}`)));
}

function show(...nodes) { root.replaceChildren(...nodes); }
function errorBox() { return h("p", { class: "error", role: "alert" }); }
function go(name) { history.pushState({}, "", "/" + name); route(); }

const views = {
  login() {
    const err = errorBox();
    const id = h("input", { id: "cid", name: "citizen_id", inputmode: "numeric", required: true });
    const pc = h("input", { id: "pc", name: "passcode", type: "password", required: true });
    const form = h("form", { class: "card", onsubmit: async (e) => {
      e.preventDefault();
      try {
        const r = await api("POST", "/api/login", { citizen_id: Number(id.value), passcode: pc.value });
        sessionStorage.setItem("token", r.token);
        go("payment-type");
      } catch (ex) { err.textContent = ex.message; }
    } },
      h("h2", {}, "Sign in"), err,
      field("Citizen ID", "cid", id), field("Passcode", "pc", pc),
      h("button", { type: "submit" }, "Sign in"));
    show(form);
  },

  "payment-type"() {
    const err = errorBox();
    const sel = h("select", { id: "pt" },
      h("option", { value: "carer_payment" }, "Carer Payment"),
      h("option", { value: "carer_allowance" }, "Carer Allowance"));
    show(stepper(1), h("form", { class: "card", onsubmit: async (e) => {
      e.preventDefault();
      try {
        const c = await api("POST", "/api/claims", { payment_type: sel.value });
        state.claimId = c.id;
        go("details");
      } catch (ex) { err.textContent = ex.message; }
    } }, h("h2", {}, "Choose a payment"), err, field("Payment type", "pt", sel), h("button", { type: "submit" }, "Continue")));
  },

  details() {
    const err = errorBox();
    const income = h("select", { id: "inc" },
      h("option", { value: "low" }, "Low"), h("option", { value: "medium" }, "Medium"), h("option", { value: "high" }, "High"));
    const hours = h("input", { id: "hrs", type: "number", min: "0", max: "168", value: "30", required: true });
    // novalidate: the API is the validator, so an out-of-range value reaches it and the person sees its error.
    show(stepper(2), h("form", { class: "card", novalidate: true, onsubmit: async (e) => {
      e.preventDefault();
      try {
        sessionStorage.setItem("result", JSON.stringify(
          await api("POST", `/api/claims/${state.claimId}/eligibility`, { income_band: income.value, caring_hours: Number(hours.value) })));
        go("eligibility");
      } catch (ex) { err.textContent = ex.message; }
    } }, h("h2", {}, "Your details"), err,
      field("Household income band", "inc", income), field("Caring hours per week", "hrs", hours),
      h("button", { type: "submit" }, "Check eligibility")));
  },

  eligibility() {
    const r = JSON.parse(sessionStorage.getItem("result") || "{}");
    const ok = r.status === "eligible";
    show(stepper(3), h("div", { class: "card" },
      h("h2", {}, "Eligibility result"),
      h("dl", {}, h("dt", {}, "Decision"), h("dd", {}, r.decision),
        h("dt", {}, "Indicative fortnightly amount"), h("dd", {}, "$" + ((r.amount_cents || 0) / 100).toFixed(2)),
        h("dt", {}, "Reason codes"), h("dd", {}, (r.reason_codes || []).join(", ") || "None")),
      r.decision === "manual_review" ? h("p", { class: "note" }, "Your claim will also be manually reviewed.") : "",
      ok ? h("button", { onclick: () => go("upload") }, "Continue")
         : h("button", { onclick: () => go("payment-type") }, "Start again")));
  },

  upload() {
    const err = errorBox();
    const file = h("input", { id: "file", type: "file", required: true });
    show(stepper(4), h("form", { class: "card", onsubmit: async (e) => {
      e.preventDefault();
      const fd = new FormData();
      fd.append("file", file.files[0]);
      try {
        await api("POST", `/api/claims/${state.claimId}/documents`, fd);
        go("review");
      } catch (ex) { err.textContent = ex.message; }
    } }, h("h2", {}, "Upload a supporting document"), err,
      h("p", {}, "Small files only, up to 1 MB."), field("Document", "file", file),
      h("button", { type: "submit" }, "Upload")));
  },

  async review() {
    const err = errorBox();
    let c;
    try { c = await api("GET", `/api/claims/${state.claimId}`); } catch (ex) { return show(stepper(5), err), (err.textContent = ex.message); }
    show(stepper(5), h("div", { class: "card" }, h("h2", {}, "Review and submit"), err,
      h("dl", {}, h("dt", {}, "Payment type"), h("dd", {}, c.payment_type),
        h("dt", {}, "Documents"), h("dd", {}, c.documents.map((d) => d.filename).join(", ") || "None"),
        h("dt", {}, "Indicative amount"), h("dd", {}, "$" + (c.eligibility_result.amount_cents / 100).toFixed(2))),
      h("button", { onclick: async () => {
        try { await api("POST", `/api/claims/${state.claimId}/submit`); go("status"); } catch (ex) { err.textContent = ex.message; }
      } }, "Submit claim")));
  },

  async status() {
    const out = h("div", { class: "card" });
    show(out);
    const render = (c) => out.replaceChildren(h("h2", {}, "Claim status"),
      h("dl", {}, h("dt", {}, "Reference"), h("dd", {}, c.reference || ""), h("dt", {}, "Status"), h("dd", {}, c.status)),
      c.status === "paid" ? h("p", { class: "note" }, "Payment has been processed.") : "",
      c.status === "failed" ? h("p", { class: "error" }, "Payment failed. Please contact the department.") : "",
      ["paid", "failed"].includes(c.status) ? h("button", { onclick: () => go("payment-type") }, "Make another claim") : "");
    for (let i = 0; i < 60; i++) {
      if (location.pathname !== "/status") return;
      const c = await api("GET", `/api/claims/${state.claimId}`).catch(() => null);
      if (c) render(c);
      if (c && ["paid", "failed"].includes(c.status)) return;
      await new Promise((r) => setTimeout(r, 2000));
    }
  },
};

const PROTECTED = new Set(["payment-type", "details", "eligibility", "upload", "review", "status"]);

function signOut() {
  sessionStorage.clear();
  go("login");
}

function syncSession() {
  const slot = document.getElementById("session");
  slot.replaceChildren(token() ? h("button", { class: "linklike", onclick: signOut }, "Sign out") : "");
}

function route() {
  let name = location.pathname.replace(/^\//, "") || "login";
  if (!views[name] || (PROTECTED.has(name) && !token())) name = "login";
  if (PROTECTED.has(name) && name !== "payment-type" && !state.claimId) name = "payment-type";
  if (location.pathname !== "/" + name) history.replaceState({}, "", "/" + name);  // every step is its own URL, so RUM sees a view per step
  stepAction("step_" + name.replace("-", "_"));
  views[name]();
  syncSession();
  syncWidget();
}

addEventListener("popstate", route);
route();
