"use strict";
// Session stays in the HttpOnly cookie. User text is rendered as text, never HTML.
const $ = id => document.getElementById(id);
let user = null, selected = null;
let serviceKind = "GROOMING";
let activePage = "work", viewRevision = 0, detailRevision = 0;
function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
function message(text, error = false) { $("message").textContent = text; $("message").className = error ? "error" : ""; $("message").setAttribute("role",error?"alert":"status"); }
function readableApiError(path,status,detail){
 if(status===401)return path==="/auth/login"?"Email or password is incorrect. Try again.":"Your session expired. Sign in again to continue.";
 if(status===403)return "You cannot use this action. Return to your work or sign in with the right account.";
 if(status===404)return "This record is no longer available. Refresh the list to continue.";
 if(status>=500)return "The service is unavailable. Check your connection and try again.";
 if(status===409)return path==="/auth/register"?"This email already has an account. Sign in instead.":"The record or availability has changed. Refresh it before trying again.";
 if(status===422){const fields=Array.isArray(detail)?detail.map(v=>v.loc?.at(-1)):[];if(fields.includes("email"))return "Enter a valid email address.";if(fields.includes("password"))return "Use a password with 10 to 128 characters.";if(fields.includes("name")||fields.includes("display_name"))return "Enter a name with 1 to 120 characters.";return "Check the entered values and dates, then try again.";}
 return "The action could not be completed. Refresh and try again.";
}
async function api(path, method = "GET", body) {
  const options = {method, credentials: "same-origin", headers: {}};
  if (body !== undefined) { options.headers["Content-Type"] = "application/json"; options.body = JSON.stringify(body); }
  const r = await fetch(path, options);
  let data;try{data=r.status===204?null:await r.json();}catch(cause){const error=new Error("The response could not be read. Refresh before trying again.");if(!r.ok)error.status=r.status;throw error;}
  if (!r.ok) {
    const detail = data.detail;
    const error = new Error(readableApiError(path,r.status,detail));
    error.status = r.status; error.detail = detail; throw error;
  }
  return data;
}
function action(fn) { return async event => {
  if (event) event.preventDefault();
  const button = event?.submitter || (event?.currentTarget?.tagName === "BUTTON" ? event.currentTarget : null);
  if (button) button.disabled = true;
  try { await fn(event); } catch (e) { message(e.message||"The action could not be completed. Try again.", true);const form=event?.currentTarget;if(form?.tagName==="FORM"&&typeof form.querySelectorAll==="function"){let note=form.querySelector(".field-error");if(!note){note=el("p",undefined,"field-error");note.id="form-error-"+form.id;note.setAttribute("role","alert");form.append(note);}note.textContent=e.message;const keys=Array.isArray(e.detail)?e.detail.map(v=>v.loc?.at(-1)):[];for(const input of form.querySelectorAll("input,select,textarea"))if(keys.includes(input.name)){input.setAttribute("aria-invalid","true");input.setAttribute("aria-describedby",note.id);input.addEventListener("input",()=>{input.removeAttribute("aria-invalid");input.removeAttribute("aria-describedby");},{once:true});}} }
  finally { if (button) button.disabled = false; }
}; }
function values(form) { return Object.fromEntries(new FormData(form)); }
function when(value) { return value ? new Intl.DateTimeFormat("en-MY",{timeZone:"Asia/Kuala_Lumpur",dateStyle:"medium",timeStyle:"short"}).format(new Date(value))+" MYT" : "—"; }
function human(value) { return value.toLowerCase().replaceAll("_", " "); }
function button(text, fn) { const b = el("button", text); b.type = "button"; b.addEventListener("click", action(fn)); return b; }
function option(value, text) { const o = el("option", text); o.value = value; return o; }
function localInstant(id) {
  const input = $(id);
  if (!input.value || !input.checkValidity()) throw new Error("Choose a valid appointment date and time.");
  return new Date(input.value).toISOString();
}
function detailGuard(kind) {
  const request = ++detailRevision, revision = viewRevision, account = user?.id;
  return () => request === detailRevision && revision === viewRevision && Boolean(account) && user?.id === account && (activePage === "work" || (user?.role === "ADMIN" && activePage === "admin-detail")) && serviceKind === kind;
}
function signedOut() {
  user = null; selected = null; activePage = "work"; ++viewRevision; ++detailRevision; $("identity").textContent = ""; $("auth").hidden = false;
  $("workspace").hidden = true; $("logout").hidden = true;
  $("detail").replaceChildren(el("p", "Select a booking to view details."));
  $("active-list").replaceChildren(); $("history-list").replaceChildren();
  $("profile").elements.display_name.value = "";
  for (const id of ["pet-maintenance","pet-select","service-select"]) $(id).replaceChildren();
  for (const id of ["notifications-panel","staff-schedule-panel","admin-review-panel","management-panel"]) $(id).replaceChildren();
  if (typeof clearCustomerView === "function") clearCustomerView();
  if (typeof clearStaffView === "function") clearStaffView();
  if (typeof clearAdminView === "function") clearAdminView();
}
async function refresh() {
  const revision = ++viewRevision; ++detailRevision; const signedIn = await api("/me");
  if (revision !== viewRevision) return; user = signedIn;
  if (typeof configureCustomerNavigation === "function") configureCustomerNavigation();
  if (typeof configureStaffNavigation === "function") configureStaffNavigation();
  if (typeof configureAdminNavigation === "function") configureAdminNavigation();
  $("identity").textContent = `${user.email} · ${human(user.role)}`;
  $("auth").hidden = true; $("workspace").hidden = false; $("logout").hidden = false;
  $("nav-inbox").hidden = user.role === "ADMIN";
  $("nav-schedule").hidden = true; $("refresh").hidden = true;
  $("nav-review").hidden = $("nav-management").hidden = user.role !== "ADMIN";
  $("customer").hidden = user.role !== "CUSTOMER" || activePage !== "work";
  $("work-section").hidden = activePage !== "work";
  for (const [page,id] of [["inbox","notifications-panel"],["schedule","staff-schedule-panel"],["review","admin-review-panel"],["management","management-panel"]]) $(id).hidden = activePage !== page;
  for (const kind of ["GROOMING", "BOARDING"]) $("nav-"+kind.toLowerCase()).setAttribute("aria-pressed", String(activePage === "work" && serviceKind === kind));
  if (typeof prepareCustomerView === "function") prepareCustomerView();
  if (typeof prepareStaffView === "function") prepareStaffView();
  if (typeof prepareAdminView === "function") prepareAdminView();
  if (user.role === "ADMIN" && activePage.startsWith("admin-")) { await renderAdminPage(revision); return; }
  if (user.role === "STAFF" && activePage.startsWith("staff-")) { await renderStaffPage(revision); return; }
  if (user.role === "CUSTOMER" && activePage.startsWith("customer-")) { await renderCustomerPage(revision); return; }
  if (activePage !== "work") { await renderOperationsPage(revision); return; }
  const serviceLabel = serviceKind === "GROOMING" ? "Grooming" : "Boarding";
  $("booking-title").textContent = `Book ${serviceLabel}`;
  $("work-title").textContent = user.role === "CUSTOMER" ? `Your ${serviceLabel} bookings` : user.role === "STAFF" ? `Your assigned ${serviceLabel} work` : `Manage ${serviceLabel} bookings`;
  $("grooming-fields").hidden = serviceKind !== "GROOMING";
  $("boarding-fields").hidden = serviceKind !== "BOARDING";
  $("appointment").required = serviceKind === "GROOMING";
  $("stay-start").required = $("stay-end").required = serviceKind === "BOARDING";
  if (user.role === "CUSTOMER") {
    const profile = await api("/customer/profile");
    if (revision !== viewRevision) return;
    $("profile").elements.display_name.value = profile.display_name;
    const pets = await api("/pets");
    if (revision !== viewRevision) return;
    $("pet-select").replaceChildren(...pets.map(p => option(p.id, p.name)));
    renderPetMaintenance(pets);
    const services = await api("/services");
    if (revision !== viewRevision) return;
    $("service-select").replaceChildren(...services.filter(s => s.service_type === serviceKind).map(s => option(s.id, s.service_type === "GROOMING" ? `${s.name} · ${s.duration_minutes} minutes` : s.name)));
  }
  const rows = await api(`/${serviceKind.toLowerCase()}/bookings`);
  if (revision !== viewRevision) return;
  for (const [id, historical] of [["active-list", false], ["history-list", true]]) {
    const relevant = rows.filter(b => ["COMPLETED", "CANCELLED", "REJECTED"].includes(b.status) === historical);
    $(id).replaceChildren(...(relevant.length ? relevant.map(b => {
      const card = el("div", undefined, "card");
      card.append(el("strong", `${b.pet_name} · ${b.service_name}`), el("p", `${human(b.status)} · ${b.booking_type === "GROOMING" ? when(b.grooming_start) : b.boarding_start+" → "+b.boarding_end}`), button("Open booking", () => show(b.id)));
      return card;
    }) : [el("p", "No bookings here yet.", "meta")]));
  }
  if (selected) await show(selected);
}
async function show(id) {
  if (serviceKind === "BOARDING") return showBoarding(id);
  const valid = detailGuard("GROOMING");
  const d = await api(`/grooming/bookings/${id}`); if (!valid()) return; selected = id;
  const b = d.booking, target = $("detail");
  target.replaceChildren(el("h2", `${d.pet_name} · ${d.service_name}`), el("p", `Customer: ${d.customer_name}`),
    el("p", `Status: ${human(b.status)}`), el("p", `Appointment: ${when(b.grooming_start)} · ${b.grooming_duration_minutes} minutes`),
    el("p", `Booking reference: ${b.id}`, "meta"));
  if (user.role === "ADMIN" && ["SUBMITTED", "CONFIRMED"].includes(b.status)) {
    const candidates = await api(`/grooming/bookings/${id}/eligible-staff`);
    if (!valid()) return;
    const select = el("select"); select.id = "assign-staff"; select.setAttribute("aria-label", "Eligible staff");
    select.append(...candidates.map(s => option(s.id, s.email)));
    if (b.assigned_staff_user_id) select.value = b.assigned_staff_user_id;
    target.append(el("h3", "Staff assignment"), select, button("Assign selected Staff", async () => {
      if (!select.value) throw new Error("No eligible Staff is available for the full appointment.");
      await api(`/admin/bookings/${id}/staff`, "PUT", {staff_user_id: select.value});
      await refresh(); message("Staff assignment saved.");
    }));
    if (b.status === "SUBMITTED") {
      for (const [label, status] of [["Confirm booking", "CONFIRMED"], ["Reject booking", "REJECTED"]]) target.append(button(label, async () => {
        await api(`/admin/bookings/${id}/status`, "POST", {status}); await refresh(); message(`Booking ${human(status)}.`);
      }));
    }
  }
  if (["STAFF", "ADMIN"].includes(user.role) && b.status === "CONFIRMED") target.append(button("Start grooming", async () => {
    await api(`/grooming/bookings/${id}/start`, "POST", {}); await refresh(); message("Grooming is now in progress.");
  }));
  if (["STAFF", "ADMIN"].includes(user.role) && b.status === "IN_PROGRESS") {
    const form = el("form"), label = el("label", "Service notes (optional, up to 4,000 characters)"), notes = el("textarea");
    notes.name = "service_notes"; notes.maxLength = 4000; label.append(notes);
    const submit = el("button", "Complete grooming"); submit.type = "submit"; form.append(label, submit);
    form.addEventListener("submit", action(async () => {
      await api(`/grooming/bookings/${id}/complete`, "POST", {service_notes: notes.value.trim() || null});
      await refresh(); message("Grooming completed. The service record and history are preserved.");
    })); target.append(form);
  }
  if (user.role === "CUSTOMER" && ["SUBMITTED", "CONFIRMED"].includes(b.status)) {
    const form = el("form"), label = el("label", "Request a new appointment (your local time)"), input = el("input");
    input.type = "datetime-local"; input.id = "reschedule-time"; input.required = true; label.append(input);
    const submit = el("button", "Request reschedule"); submit.type = "submit"; form.append(label, submit);
    form.addEventListener("submit", action(async () => {
      await api(`/bookings/${id}/reschedule`, "POST", {grooming_start: localInstant("reschedule-time")});
      await refresh(); message("Rescheduled request submitted. Staff assignment and Admin confirmation are required again.");
    })); target.append(form, button("Cancel booking", async () => {
      await api(`/bookings/${id}/cancel`, "POST"); await refresh(); message("Booking cancelled; history preserved.");
    }));
  }
  if (d.grooming_record) {
    const r = d.grooming_record;
    target.append(el("h3", "Service record"), el("p", `Started: ${when(r.started_at)}`),
      el("p", `Start actor: ${r.started_by_user_id}`, "meta"));
    if (r.completed_at) target.append(el("p", `Completed: ${when(r.completed_at)}`),
      el("p", `Completion actor: ${r.completed_by_user_id}`, "meta"), el("p", r.service_notes || "No service notes recorded.", "notes"));
  }
  const history = el("ol");
  for (const e of d.history) {
    const item = el("li", `${human(e.event_type)} · ${when(e.created_at)}`);
    item.append(el("div", `${e.old_status || "—"} → ${e.new_status || "—"} · Actor: ${e.actor_user_id}`, "meta")); history.append(item);
  }
  target.append(el("h3", "Booking history"), history);
}
$("login").addEventListener("submit", action(async e => {
  const form = e.currentTarget; await api("/auth/login", "POST", values(form)); form.reset(); selected = null; await refresh(); message("Signed in.");
}));
$("register").addEventListener("submit", action(async e => {
  const form = e.currentTarget, data = values(form); await api("/auth/register", "POST", data);
  await api("/auth/login", "POST", {email: data.email, password: data.password}); form.reset();
  selected = null; await refresh(); message("Account created. Add your pet and choose a service.");
}));
$("logout").addEventListener("click", action(async () => { await api("/auth/logout", "POST"); signedOut(); message("Signed out."); }));
$("refresh").addEventListener("click", action(async () => { await refresh(); message("Updated."); }));
$("profile").addEventListener("submit", action(async e => { await api("/customer/profile", "PUT", values(e.currentTarget)); message("Profile saved."); }));
$("pet").addEventListener("submit", action(async e => { const form = e.currentTarget; await api("/pets", "POST", values(form)); form.reset(); await refresh(); message("Pet added."); }));
function requestedSchedule() {
  if (!$("service-select").value) throw new Error("An active service is required.");
  const service_id = $("service-select").value;
  if (serviceKind === "GROOMING") return {service_id, grooming_start: localInstant("appointment")};
  if (!$("stay-start").value || !$("stay-end").value) throw new Error("Choose both stay dates.");
  return {service_id, boarding_start: $("stay-start").value, boarding_end: $("stay-end").value};
}
$("availability").addEventListener("click", action(async () => {
  const result = await api("/availability", "POST", requestedSchedule()); message(result.available ? (serviceKind === "GROOMING" ? `Available for ${result.duration_minutes} minutes. Submit a booking request to continue.` : "Boarding capacity is available for the requested dates. Submit a booking request to continue.") : "No availability for the requested period.");
}));
$("booking").addEventListener("submit", action(async () => {
  await customerGo("book");
}));
for (const kind of ["GROOMING", "BOARDING"]) $("nav-"+kind.toLowerCase()).addEventListener("click", action(async () => {
  serviceKind = kind; selected = null; activePage = "work";
  $("detail").replaceChildren(el("p", "Select a booking to view details."));
  await refresh(); message(`${kind === "GROOMING" ? "Grooming" : "Boarding"} workflow selected.`);
}));
// All deferred workflow scripts must exist before the initial authenticated render.
document.addEventListener("DOMContentLoaded", async () => {
  const revision = viewRevision + 1;
  try { await refresh(); } catch (error) { if (viewRevision === revision) signedOut(); }
});
