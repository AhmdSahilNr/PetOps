"use strict";
// Shares existing safe text rendering, cookie-session API and role navigation.
async function showBoarding(id) {
  const valid = detailGuard("BOARDING");
  const d = await api(`/boarding/bookings/${id}`); if (!valid()) return; selected = id;
  const b = d.booking, target = $("detail");
  target.replaceChildren(el("h2", `${d.pet_name} · ${d.service_name}`), el("p", `Customer: ${d.customer_name}`),
    el("p", `Status: ${human(b.status)}`), el("p", `Reserved dates: ${b.boarding_start} → ${b.boarding_end} (end exclusive)`),
    el("p", `Booking reference: ${b.id}`, "meta"));
  if (user.role === "ADMIN" && ["SUBMITTED", "CONFIRMED"].includes(b.status)) {
    const units = await api("/admin/boarding-availability", "POST", {service_id:b.service_id, boarding_start:b.boarding_start, boarding_end:b.boarding_end});
    if (!valid()) return;
    const select = el("select"); select.setAttribute("aria-label", "Boarding accommodation");
    select.append(...units.map(u => option(u.accommodation_id, `${u.name} · ${u.available_places} unreserved places`)));
    const current = d.allocation_history.find(a => !a.released_at);
    if (current) select.value = current.accommodation_id;
    target.append(el("h3", "Accommodation"), el("p", "The current allocation is already counted in reserved capacity. Allocation is validated again when saved.", "meta"),
      select, button("Allocate accommodation", async () => {
        if (!select.value) throw new Error("No active accommodation is configured.");
        await api(`/admin/bookings/${id}/accommodation`, "PUT", {accommodation_id:select.value});
        await refresh(); message("Accommodation allocated.");
      }));
    const staff = await api("/boarding/staff-options"), picker = el("select");
    if (!valid()) return;
    picker.setAttribute("aria-label", "Optional boarding staff"); picker.append(option("", "No Staff assignment (Admin operates stay)"), ...staff.map(s => option(s.id, s.email)));
    picker.value = b.assigned_staff_user_id || "";
    const form = el("form"), startLabel = el("label", "Duty start (local time, inside stay)"), start = el("input"), endLabel = el("label", "Duty end (local time, inside stay)"), end = el("input");
    start.type = end.type = "datetime-local"; start.value = localTimeInput(b.staff_start); end.value = localTimeInput(b.staff_end); startLabel.append(start); endLabel.append(end);
    const save = el("button", "Save optional Staff assignment"); save.type = "submit";
    form.append(el("h3", "Optional Staff duty"), picker, startLabel, endLabel, save);
    form.addEventListener("submit", action(async () => {
      const payload = {staff_user_id:picker.value || null};
      if (picker.value) {
        if (!start.value || !end.value) throw new Error("Choose both duty times inside the reserved stay.");
        payload.starts_at = new Date(start.value).toISOString(); payload.ends_at = new Date(end.value).toISOString();
      }
      await api(`/admin/bookings/${id}/staff`, "PUT", payload); await refresh(); message("Boarding Staff assignment saved.");
    })); target.append(form);
    if (b.status === "SUBMITTED") for (const [label, status] of [["Confirm booking", "CONFIRMED"], ["Reject booking", "REJECTED"]]) target.append(button(label, async () => {
      await api(`/admin/bookings/${id}/status`, "POST", {status}); await refresh(); message(`Booking ${human(status)}.`);
    }));
  }
  if (["STAFF", "ADMIN"].includes(user.role)) {
    const next = {CONFIRMED:["Check in", "check-in"], CHECKED_IN:["Check out", "check-out"], STAYING:["Check out", "check-out"]}[b.status];
    if (next) target.append(button(next[0], async () => {
      await api(`/boarding/bookings/${id}/${next[1]}`, "POST", {}); await refresh(); message(`${next[0]} recorded.`);
    }));
    if (["CHECKED_IN", "STAYING"].includes(b.status)) {
      const form = el("form"), label = el("label", "Stay update (up to 4,000 characters)"), note = el("textarea"), submit = el("button", "Add stay update");
      note.required = true; note.maxLength = 4000; label.append(note); submit.type = "submit"; form.append(label, submit);
      form.addEventListener("submit", action(async () => {
        await api(`/boarding/bookings/${id}/notes`, "POST", {note:note.value}); await refresh(); message("Stay update preserved.");
      })); target.append(form);
    }
  }
  if (user.role === "CUSTOMER" && ["SUBMITTED", "CONFIRMED"].includes(b.status)) {
    const form = el("form"), startLabel = el("label", "New stay start date"), start = el("input"), endLabel = el("label", "New stay end date (exclusive)"), end = el("input"), submit = el("button", "Request reschedule");
    start.type = end.type = "date"; start.required = end.required = true; startLabel.append(start); endLabel.append(end); submit.type = "submit"; form.append(startLabel, endLabel, submit);
    form.addEventListener("submit", action(async () => {
      await api(`/bookings/${id}/reschedule`, "POST", {boarding_start:start.value, boarding_end:end.value});
      await refresh(); message("Changed request submitted. Accommodation allocation and Admin confirmation are required again.");
    })); target.append(form, button("Cancel booking", async () => {
      await api(`/bookings/${id}/cancel`, "POST"); await refresh(); message("Booking cancelled; history preserved.");
    }));
  }
  target.append(el("h3", "Accommodation history"));
  for (const a of d.allocation_history) target.append(el("p", `${a.name} · ${a.starts_on} → ${a.ends_on} · ${a.released_at ? "released "+when(a.released_at) : "reserved"}`));
  if (d.boarding_stay) {
    target.append(el("h3", "Stay record"));
    for (const [step, label] of [["checked_in", "Checked in"], ["stay_started", "Stay started"], ["checked_out", "Checked out"], ["completed", "Completed"]]) {
      if (d.boarding_stay[step+"_at"]) target.append(el("p", `${label}: ${when(d.boarding_stay[step+"_at"])}`), el("p", `Actor: ${d.boarding_stay[step+"_by_user_id"]}`, "meta"));
    }
  }
  target.append(el("h3", "Stay updates"));
  for (const n of d.stay_notes) target.append(el("p", n.note, "notes"), el("p", `${when(n.created_at)} · Actor: ${n.actor_user_id}`, "meta"));
  if (!d.stay_notes.length) target.append(el("p", "No stay updates recorded.", "meta"));
  target.append(el("h3", "Booking history")); const history = el("ol");
  for (const e of d.history) { const item = el("li", `${human(e.event_type)} · ${when(e.created_at)}`); item.append(el("div", `${e.old_status || "—"} → ${e.new_status || "—"} · Actor: ${e.actor_user_id}`, "meta")); history.append(item); }
  target.append(history);
}
