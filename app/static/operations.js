"use strict";
// New role panels share the existing cookie API and text-only DOM helpers.
for (const [id,page] of [["nav-inbox","inbox"],["nav-schedule","schedule"],["nav-review","review"],["nav-management","management"]]) {
  $(id).addEventListener("click",action(async () => { activePage=user?.role==="CUSTOMER"&&page==="inbox"?"customer-notifications":user?.role==="STAFF"?({inbox:"staff-notifications",schedule:"staff-availability"}[page]||page):page; selected=null; await refresh(); message(""); }));
}
function table(headers,rows) {
  const t=el("table"), head=el("tr"); for (const h of headers) head.append(el("th",h)); t.append(head);
  for (const row of rows) { const tr=el("tr"); for (const cell of row) tr.append(el("td",String(cell ?? "—"))); t.append(tr); }
  return t;
}
function localTimeInput(value) {
  if (!value) return ""; const d=new Date(value); return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);
}
function businessDate() {
  const parts=new Intl.DateTimeFormat("en",{timeZone:"Asia/Kuala_Lumpur",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date());
  const value=type=>parts.find(p=>p.type===type).value; return `${value("year")}-${value("month")}-${value("day")}`;
}
// A compact form helper; no HTML strings or executable user content.
function operationForm(title,fields,label,submit) {
  const form=el("form"); form.append(el("h3",title)); const inputs={};
  for (const f of fields) {
    const wrapper=el("label",f.label), input=el(f.type==="select" ? "select" : f.type==="textarea" ? "textarea" : "input");
    if (!["select","textarea"].includes(f.type)) input.type=f.type || "text";
    input.name=f.name; input.required=Boolean(f.required);
    if (f.type==="select") input.append(...f.options.map(o=>option(o.value,o.text)));
    if (f.type==="checkbox") input.checked=Boolean(f.value); else input.value=f.value ?? "";
    if (f.maxLength) input.maxLength=f.maxLength; if (f.min!==undefined) input.min=f.min; if (f.max!==undefined) input.max=f.max;
    if (f.type==="number") input.step="1"; if (f.type==="password") input.autocomplete="new-password";
    wrapper.append(input); form.append(wrapper); inputs[f.name]=input;
  }
  const b=el("button",label); b.type="submit"; form.append(b);
  form.addEventListener("submit",action(async () => {
    const data={}; for (const f of fields) data[f.name]=f.type==="checkbox" ? inputs[f.name].checked : f.type==="number" ? (inputs[f.name].value==="" ? null : Number(inputs[f.name].value)) : inputs[f.name].value;
    await submit(data,form);
  })); return form;
}
function renderPetMaintenance(pets) {
  const target=$("pet-maintenance"); target.replaceChildren(el("h3","Your pets"));
  for (const p of pets) {
    const form=operationForm(`Edit ${p.name}`,[{label:"Pet name",name:"name",value:p.name,required:true,maxLength:120}],"Save pet",async data=>{
      await api(`/pets/${p.id}`,"PUT",data); await refresh(); message("Pet updated.");
    });
    form.append(button("Delete pet without booking history",async () => { await api(`/pets/${p.id}`,"DELETE"); await refresh(); message("Pet deleted."); })); target.append(form);
  }
}
async function renderOperationsPage(revision) {
  const valid=()=>revision===viewRevision && user;
  if (activePage==="inbox") {
    const data=await api("/notifications"); if (!valid()) return;
    const target=$("notifications-panel"); target.replaceChildren(el("h1",`Your notifications · ${data.unread_count} unread`),el("p","Notices reflect their event time. Open the booking for its current status."));
    for (const n of data.items) {
      const card=el("article"); card.append(el("h3",human(n.kind)),el("p",n.message),el("p",`${when(n.created_at)} · ${n.read_at ? "read" : "unread"}`,"meta"));
      if (!n.read_at) card.append(button("Mark as read",async () => { await api(`/notifications/${n.id}/read`,"POST",{}); await refresh(); }));
      card.append(button("Open permitted booking",async () => {
        // Fetch scoped detail before switching panels; former assignments stay denied.
        await api(`/${n.booking_type.toLowerCase()}/bookings/${n.booking_id}`);
        serviceKind=n.booking_type; activePage="work"; selected=n.booking_id; await refresh();
      })); target.append(card);
    }
    if (!data.items.length) target.append(el("p","No notifications yet."));
    if (data.items.length===data.limit) target.append(el("p","Showing the latest 100 notices. Older notices remain stored."));
  } else if (activePage==="schedule") {
    const windows=await api("/staff/availability"); if (!valid()) return;
    $("staff-schedule-panel").replaceChildren(el("h1","Your recorded availability"),el("p","Admin maintains these windows. Assigned work is available through Grooming and Boarding navigation."),table(["Start","End","Active"],windows.map(w=>[when(w.starts_at),when(w.ends_at),w.is_active ? "Yes" : "No"])));
  } else if (activePage==="management") {
    const [staff,services,units,setting,audit]=await Promise.all([api("/admin/staff"),api("/admin/services"),api("/admin/accommodations"),api("/admin/notification-settings"),api("/admin/management-history?limit=20")]);
    if (!valid()) return; const target=$("management-panel"); target.replaceChildren(el("h1","Admin management"));
    target.append(operationForm("Create Staff account",[{label:"Staff email",name:"email",type:"email",required:true},{label:"Initial password (10–128 characters)",name:"password",type:"password",required:true,maxLength:128},{label:"Active",name:"is_active",type:"checkbox",value:true}],"Create Staff",async (data,form)=>{
      await api("/admin/staff","POST",data); form.reset(); await refresh(); message("Staff account created.");
    }));
    for (const s of staff) target.append(operationForm(`Staff: ${s.email}`,[{label:"Staff email",name:"email",type:"email",required:true,value:s.email},{label:"Active",name:"is_active",type:"checkbox",value:s.is_active},{label:"New password (leave blank to keep)",name:"password",type:"password",maxLength:128}],"Save Staff",async data=>{
      if (!data.password) delete data.password; await api(`/admin/staff/${s.id}`,"PUT",data); await refresh(); message("Staff updated. Deactivation and password changes revoke old sessions.");
    }));
    const duration={label:"Grooming duration in minutes (blank for Boarding)",name:"duration_minutes",type:"number",min:1,max:2147483647};
    target.append(operationForm("Create service",[{label:"Service name",name:"name",required:true,maxLength:120},{label:"Service type",name:"service_type",type:"select",options:[{value:"GROOMING",text:"Grooming"},{value:"BOARDING",text:"Boarding"}]},{label:"Active",name:"is_active",type:"checkbox",value:true},duration],"Create service",async (data,form)=>{ await api("/admin/services","POST",data); form.reset(); await refresh(); message("Service created."); }));
    for (const s of services) target.append(operationForm(`Service: ${s.name} (${human(s.service_type)})`,[{label:"Service name",name:"name",required:true,maxLength:120,value:s.name},{label:"Active",name:"is_active",type:"checkbox",value:s.is_active},{...duration,value:s.duration_minutes}],"Save service",async data=>{ await api(`/admin/services/${s.id}`,"PUT",data); await refresh(); message("Service updated; previous booking duration snapshots are retained."); }));
    target.append(operationForm("Reminder settings",[{label:"Enable in-system reminders",name:"enabled",type:"checkbox",value:setting.enabled},{label:"Lead time in minutes (Admin chooses)",name:"lead_minutes",type:"number",min:1,max:525600,value:setting.lead_minutes}],"Save reminder settings",async data=>{ await api("/admin/notification-settings","PUT",data); await refresh(); message("Reminder settings saved."); }));
    target.append(el("p",setting.boarding_reference),button("Create due reminders now",async () => { const r=await api("/admin/reminders/run","POST",{}); message(`${r.created} due reminders created. Repeated checks do not duplicate a confirmation cycle.`); }));
    const availability=el("section"), picker=el("select"); picker.setAttribute("aria-label","Staff availability account"); picker.append(...staff.map(s=>option(s.id,s.email))); availability.append(el("h2","Staff availability"),picker); target.append(availability);
    const windows=el("div"); availability.append(windows);
    async function loadWindows() {
      if (!picker.value) return; const account=picker.value, rows=await api(`/admin/staff/${account}/availability`); if (!valid()) return;
      const fields=w=>[{label:"Window start (local time)",name:"starts_at",type:"datetime-local",required:true,value:localTimeInput(w?.starts_at)},{label:"Window end (local time)",name:"ends_at",type:"datetime-local",required:true,value:localTimeInput(w?.ends_at)},{label:"Active window",name:"is_active",type:"checkbox",value:w ? w.is_active : true}];
      function body(data) { return {...data,starts_at:new Date(data.starts_at).toISOString(),ends_at:new Date(data.ends_at).toISOString()}; }
      windows.replaceChildren(operationForm("Add availability",fields(),"Add availability",async data=>{ await api(`/admin/staff/${account}/availability`,"POST",body(data)); await loadWindows(); message("Availability added."); }));
      for (const w of rows) windows.append(operationForm("Recorded window",fields(w),"Save availability",async data=>{ await api(`/admin/staff/${account}/availability/${w.id}`,"PUT",body(data)); await loadWindows(); message("Availability saved."); }));
    }
    picker.addEventListener("change",action(loadWindows)); await loadWindows();
    const unitFields=u=>[{label:"Unit name",name:"name",required:true,maxLength:120,value:u?.name},{label:"Category",name:"category",required:true,maxLength:120,value:u?.category},{label:"Capacity",name:"capacity",type:"number",required:true,min:1,max:2147483647,value:u?.capacity},{label:"Active unit",name:"is_active",type:"checkbox",value:u ? u.is_active : true},{label:"Suitability notes (optional)",name:"notes",type:"textarea",value:u?.notes}];
    target.append(operationForm("Create accommodation",unitFields(),"Create accommodation",async data=>{ data.notes=data.notes || null; await api("/admin/accommodations","POST",data); await refresh(); message("Accommodation created."); }));
    for (const u of units) target.append(operationForm(`Accommodation: ${u.name}`,unitFields(u),"Save accommodation",async data=>{ data.notes=data.notes || null; await api(`/admin/accommodations/${u.id}`,"PUT",data); await refresh(); message("Accommodation updated."); }));
    target.append(el("h2","Recent management actions"),table(["Action","Target","Actor","When"],audit.map(e=>[human(e.action),e.details.new?.email || e.details.new?.name || "Reminder settings",e.actor_email,when(e.created_at)])));
  } else if (activePage==="review") {
    await renderReview(revision);
  }
}
async function renderReview(revision,mode="all") {
  const target=$("admin-review-panel"), today=businessDate(); target.replaceChildren(el("h1",mode==="overview"?"Overview":"Admin operational review"));
  const result=el("section"), history=el("section");
  const period=operationForm("Reporting period (Asia/Kuala_Lumpur)",[{label:"From date",name:"from_date",type:"date",required:true,value:today.slice(0,8)+"01"},{label:"To date",name:"to_date",type:"date",required:true,value:today}],"Update dashboard",loadReport);
  target.append(period,result);if(mode!=="overview")target.append(history);
  async function loadReport(data) {
    const d=await api(`/admin/dashboard?${new URLSearchParams(data)}`); if (revision!==viewRevision) return;
    result.replaceChildren(el("h2",`Created bookings: ${d.total_bookings}`),table(["Current status of period cohort","Count"],Object.entries(d.bookings_by_status).map(([k,v])=>[human(k),v])),
      table(["Service","Created in period","Completed in period"],["GROOMING","BOARDING"].map(k=>[human(k),d.bookings_by_type[k],d.completed_services_by_type[k]])),
      el("p",`Cancellation events: ${d.booking_change_events.BOOKING_CANCELLED} · Reschedule events: ${d.booking_change_events.BOOKING_RESCHEDULED}`),
      el("h2","Current Boarding snapshot"),el("p",`As of ${when(d.boarding_current.as_of)} · ${d.boarding_current.physically_occupied} occupied / ${d.boarding_current.configured_active_capacity} active configured places · ${d.boarding_current.available_places} available · utilisation ${d.boarding_current.utilisation_percent ?? "not configured"}${d.boarding_current.utilisation_percent===null ? "" : "%"}`),
      el("p",d.definitions.boarding_current),table(["Unit","Capacity","Occupied","Available"],d.boarding_current.units.map(u=>[u.name,u.configured_capacity,u.physically_occupied,u.available_places])),
      el("h2","Current assignments scheduled in period"),table(["Staff","Active assigned bookings","Without recorded period"],d.staff_workload.map(s=>[s.email,s.active_assigned_bookings_in_period,s.active_assignments_without_recorded_period])),
      el("p",`Upcoming arrivals in period: ${d.upcoming_arrivals.total} · departures: ${d.upcoming_departures.total}`),
      table(["Planned arrival","Booking","Status"],d.upcoming_arrivals.items.map(b=>[b.boarding_start,b.id,human(b.status)])),table(["Planned departure","Booking","Status"],d.upcoming_departures.items.map(b=>[b.boarding_end,b.id,human(b.status)])),
      el("p",d.definitions.bookings),el("p",d.definitions.completed_services),el("p",d.definitions.changes),el("p",d.definitions.workload));
  }
  if(mode==="overview"){await loadReport({from_date:today.slice(0,8)+"01",to_date:today});return;}
  const customers=await api("/admin/customers"); if (revision!==viewRevision) return;
  const owner=el("select"),pet=el("select"); owner.setAttribute("aria-label","History Customer");pet.setAttribute("aria-label","History pet");
  owner.append(option("","All permitted Customers"),...customers.map(c=>option(c.id,`${c.display_name} · ${c.email}`)));pet.append(option("","All selected Customer pets"));
  const list=el("div"),detail=el("article");history.append(el("h2","Customer and Pet history"),owner,pet,button("Find history",loadHistory),list,detail);
  owner.addEventListener("change",action(async () => { const pets=owner.value ? await api(`/admin/customers/${owner.value}/pets`) : []; pet.replaceChildren(option("","All selected Customer pets"),...pets.map(p=>option(p.id,p.name))); }));
  async function loadHistory() {
    const params=new URLSearchParams();if (owner.value) params.set("customer_id",owner.value);if (pet.value) params.set("pet_id",pet.value);
    const rows=await api(`/admin/history?${params}`);if (revision!==viewRevision) return;
    list.replaceChildren();detail.replaceChildren();for (const b of rows.items) {
      const card=el("div",undefined,"card");card.append(el("p",`${b.customer_name} · ${b.pet_name} · ${b.service_name} · ${human(b.status)}`),button("Review booking history",async () => {
        const d=await api(`/admin/bookings/${b.id}/history`);if (revision!==viewRevision) return;
        detail.replaceChildren(el("h3",`${d.pet_name} · ${d.service_name}`),el("p",`Customer: ${d.customer_name} · Status: ${human(d.booking.status)}`),table(["Event","Old status","New status","Actor","When"],d.history.map(e=>[human(e.event_type),e.old_status,e.new_status,e.actor_user_id,when(e.created_at)])));
        if (d.grooming_record?.service_notes) detail.append(el("p",d.grooming_record.service_notes,"notes"));for (const n of d.stay_notes || []) detail.append(el("p",n.note,"notes"));
        if (["SUBMITTED","CONFIRMED"].includes(b.status)) {
          detail.append(button("Cancel before work begins",async () => { await api(`/admin/bookings/${b.id}/cancel`,"POST",{});await loadHistory();message("Cancellation recorded with owning Customer notification."); }));
          const fields=b.booking_type==="GROOMING" ? [{label:"New appointment (local time)",name:"grooming_start",type:"datetime-local",required:true}] : [{label:"New Boarding start",name:"boarding_start",type:"date",required:true},{label:"New Boarding end",name:"boarding_end",type:"date",required:true}];
          detail.append(operationForm("Reschedule before work begins",fields,"Submit changed request",async data=>{ if (data.grooming_start) data.grooming_start=new Date(data.grooming_start).toISOString();await api(`/admin/bookings/${b.id}/reschedule`,"POST",data);await loadHistory();message("Changed request requires resource validation and confirmation again."); }));
        }
      }));list.append(card);
    }
    if (!rows.items.length) list.append(el("p","No matching history."));if (rows.items.length===rows.limit) list.append(el("p","Showing the first 100 results; use Customer/Pet filters to narrow."));
  }
  await loadReport({from_date:today.slice(0,8)+"01",to_date:today}); await loadHistory();
}
