"use strict";
// Customer-only presentation over existing scoped APIs. No new lifecycle or notice semantics.
let customerRecordFilter="auto",customerRecordType="ALL",customerRecordEdit=null,customerNoticeOffset=0;
function resetCustomerRecordEdit(){customerRecordEdit=null;}
function resetCustomerRecords(){customerRecordFilter="auto";customerRecordType="ALL";customerRecordEdit=null;customerNoticeOffset=0;}
const recordLabels={SUBMITTED:"Requested",CONFIRMED:"Confirmed",IN_PROGRESS:"In progress",CHECKED_IN:"Staying",STAYING:"Staying",CHECKED_OUT:"Completed",COMPLETED:"Completed",CANCELLED:"Cancelled",REJECTED:"Rejected"};
function recordLabel(status){return recordLabels[status]||human(status).replace(/^./,c=>c.toUpperCase());}
function recordBadge(status){const badge=customerStatus(status);badge.textContent=recordLabel(status);return badge;}
function recordTime(value){return value?new Intl.DateTimeFormat("en-MY",{timeZone:"Asia/Kuala_Lumpur",dateStyle:"medium",timeStyle:"short"}).format(new Date(value))+" MYT":"Not recorded";}
function recordDate(value){return new Intl.DateTimeFormat("en-MY",{timeZone:"UTC",dateStyle:"medium"}).format(new Date(value+"T00:00:00Z"));}
function recordSchedule(b){return b.booking_type==="GROOMING"?recordTime(b.grooming_start):recordDate(b.boarding_start)+" → "+recordDate(b.boarding_end);}
function recordLocal(value){return new Date(new Date(value).getTime()+8*3600000).toISOString().slice(0,16);}
function recordError(error){if(error.status===404)return "This booking or notification is no longer available to your account.";if(error.status===409){if(/available Staff|conflicting assignment/i.test(error.message))return "No Staff member is available for the full new appointment. Choose another date or time.";if(/accommodation.*capacity/i.test(error.message))return "No accommodation has space throughout the new stay. Choose another date range.";return "The booking has changed or this action is no longer permitted. Check its current status before trying again.";}if(error.status===422){if(/service.*active/i.test(error.message))return "This service is no longer active, so it cannot be rescheduled. Cancellation still depends on the booking status.";return "Check your new dates. Grooming must be in the future; checkout must be after check-in, with no past check-in date.";}return "We couldn’t load this information. Check your connection and try again.";}
function recordEmpty(title,text,actionButton){const section=el("section",undefined,"record-empty");section.append(el("h2",title),el("p",text,"meta"));if(actionButton)section.append(actionButton);return section;}
async function renderCustomerRecords(revision){
 const page=activePage,account=user.id,id=selected,kind=serviceKind;
 const valid=()=>revision===viewRevision&&user?.id===account&&user?.role==="CUSTOMER"&&activePage===page&&(page!=="customer-detail"||(selected===id&&serviceKind===kind));
 customerPanel.setAttribute("aria-busy","true");const loading=el("p","Loading your bookings…","meta");loading.setAttribute("role","status");customerPanel.replaceChildren(loading);
 try{
  if(page==="customer-bookings"){
   const [grooming,boarding]=await Promise.all([api("/grooming/bookings"),api("/boarding/bookings")]);if(!valid())return;drawCustomerBookingList([...grooming,...boarding]);
  }else if(page==="customer-detail"){
   const data=await api(`/${kind.toLowerCase()}/bookings/${id}`);if(!valid())return;drawCustomerBookingDetail(data,valid);
  }else{
   const data=await api(`/notifications?limit=10&offset=${customerNoticeOffset}`);if(!valid())return;drawCustomerNotifications(data,valid);
  }
 }catch(error){if(!valid())return;if(error.status===401){signedOut();message("Your session expired. Sign in again to continue.",true);return;}
  customerPanel.replaceChildren(customerHeading("Your information is unavailable",recordError(error)),quiet("Try again",()=>refresh()),quiet("My Bookings",()=>customerGo("bookings")));message(recordError(error),true);
 }finally{if(valid())customerPanel.removeAttribute("aria-busy");}
}
function drawCustomerBookingList(rows){
 customerPanel.replaceChildren(customerHeading("My Bookings","",button("Book a service",()=>customerGo("book"))));
 const terminal=b=>["COMPLETED","CANCELLED","REJECTED","CHECKED_OUT"].includes(b.status),current=rows.filter(b=>!terminal(b)),history=rows.filter(terminal);
 if(!rows.length){customerPanel.append(recordEmpty("No bookings yet","Choose a service to request your first booking.",button("Book a service",()=>customerGo("book"))));return;}
 if(customerRecordFilter==="auto")customerRecordFilter=current.length?"current":"history";
 const filters=el("div",undefined,"record-filters");filters.setAttribute("role","group");filters.setAttribute("aria-label","Booking view");
 for(const [key,label,count]of [["current","Current",current.length],["history","History",history.length],["all","All",rows.length]]){const b=quiet(label+" ("+count+")",()=>{customerRecordFilter=key;drawCustomerBookingList(rows);});b.setAttribute("aria-pressed",String(customerRecordFilter===key));filters.append(b);}
 const label=el("label","Service type"),type=el("select");type.setAttribute("aria-label","Service type");type.append(option("ALL","All services"),option("GROOMING","Grooming"),option("BOARDING","Boarding"));type.value=customerRecordType;type.addEventListener("change",()=>{customerRecordType=type.value;drawCustomerBookingList(rows);});label.append(type);filters.append(label);customerPanel.append(filters);
 customerPanel.append(el("p",customerRecordFilter==="history"?"Completed, cancelled and rejected records. Ordered by planned visit date.":"Includes requests and ongoing work, even if the planned date has passed.","meta"));
 const relevant=rows.filter(b=>(customerRecordFilter==="all"||(customerRecordFilter==="history")===terminal(b))&&(customerRecordType==="ALL"||b.booking_type===customerRecordType));
 const instant=b=>new Date(b.grooming_start||b.boarding_start+"T00:00:00+08:00").getTime();const active=b=>["IN_PROGRESS","CHECKED_IN","STAYING"].includes(b.status)?0:1;
 relevant.sort((a,b)=>(customerRecordFilter==="history"?instant(b)-instant(a):active(a)-active(b)||instant(a)-instant(b))||a.id.localeCompare(b.id));
 if(!relevant.length){customerPanel.append(recordEmpty("Nothing in this view.","Your other bookings are still available.",quiet("Show all bookings",()=>{customerRecordFilter="all";customerRecordType="ALL";drawCustomerBookingList(rows);})));return;}
 const list=el("div",undefined,"customer-booking-list");for(const b of relevant){const row=el("section",undefined,"customer-booking-row"),identity=el("div",undefined,"record-pet");identity.append(petAvatar(b.pet_name),el("h2",b.pet_name));const names=el("div");names.append(identity,el("p",b.service_name,"record-service"),el("p",b.booking_type==="GROOMING"?"Grooming":"Boarding","meta"));const schedule=el("div");schedule.append(el("p",recordSchedule(b)),el("p",b.booking_type==="GROOMING"?b.grooming_duration_minutes+" minutes":"Check-in → checkout","meta"));row.append(names,schedule,recordBadge(b.status),quiet("View booking",()=>openCustomerBooking(b)));list.append(row);}customerPanel.append(list);
}
function recordDefinition(rows){const dl=el("dl",undefined,"record-summary");for(const [label,value]of rows)dl.append(el("dt",label),el("dd",value));return dl;}
function recordFeedback(text){const node=$("record-feedback");if(node){node.textContent=text;node.hidden=false;node.focus();}}
function drawCustomerBookingDetail(data,valid){
 const b=data.booking,changeable=["SUBMITTED","CONFIRMED"].includes(b.status);
 customerPanel.replaceChildren(quiet("Back to My Bookings",()=>customerGo("bookings")),customerHeading(data.pet_name,data.service_name),recordBadge(b.status));
 const facts=[["Service",data.service_name],["Service type",b.booking_type==="GROOMING"?"Grooming":"Boarding"]];
 if(b.booking_type==="GROOMING")facts.push(["Appointment",recordTime(b.grooming_start)],["Duration",b.grooming_duration_minutes+" minutes"]);else facts.push(["Check-in date",recordDate(b.boarding_start)],["Checkout date",recordDate(b.boarding_end)]);
 customerPanel.append(recordDefinition(facts));
 const next={SUBMITTED:"Your request is awaiting Admin review. It is not confirmed yet.",CONFIRMED:"Your booking is confirmed. You can request a new date or cancel before work begins.",IN_PROGRESS:"Grooming is in progress. Dates and cancellation can no longer be changed.",CHECKED_IN:"Your pet has checked in. Dates and cancellation can no longer be changed.",STAYING:"Your pet’s stay is in progress.",CHECKED_OUT:"Checkout has been recorded. Final completion is still pending.",COMPLETED:"This service is complete. Your record and history remain available.",CANCELLED:"Booking cancelled.",REJECTED:"This request was not accepted. Its history is kept."};customerPanel.append(el("p",next[b.status]||"See your current booking status above.","record-next"));
 const feedback=el("p",undefined,"booking-feedback");feedback.id="record-feedback";feedback.hidden=true;feedback.tabIndex=-1;feedback.setAttribute("role","alert");customerPanel.append(feedback);
 async function mutate(operation,payload){if(customerRecordEdit?.busy)return;const mode=customerRecordEdit;mode.busy=true;for(const control of customerPanel.querySelectorAll(".record-change button"))control.disabled=true;
  try{await api(`/bookings/${b.id}/${operation}`,"POST",payload);if(!valid())return;customerRecordEdit=null;await refresh();message(operation==="cancel"?"Booking cancelled. Your history is preserved.":"Reschedule request submitted. Admin must review and confirm it again.");
  }catch(error){if(!valid())return;if(error.status===401){signedOut();message("Your session expired. Sign in again and check the booking before retrying.",true);return;}
   if(!error.status||error.status>=500){customerRecordEdit={kind:"unknown"};drawCustomerBookingDetail(data,valid);recordFeedback("We couldn’t confirm whether the change was saved. Refresh this booking before trying again.");}
   else if([404,409].includes(error.status)){customerRecordEdit=null;await refresh();message(recordError(error),true);}
   else{mode.busy=false;for(const control of customerPanel.querySelectorAll(".record-change button"))control.disabled=false;recordFeedback(recordError(error));}
  }
 }
 const changes=el("section",undefined,"record-change");
 if(customerRecordEdit?.kind==="unknown"){changes.append(button("Refresh booking",async()=>{customerRecordEdit=null;await refresh();}));}
 else if(changeable&&customerRecordEdit?.kind==="cancel"){
  changes.append(el("h2","Cancel this booking?"),el("p","This cancels the booking. Any assigned reservation is released, and the history is kept."),button("Confirm cancellation",()=>mutate("cancel")),quiet("Keep booking",()=>{customerRecordEdit=null;drawCustomerBookingDetail(data,valid);}));
 }else if(changeable&&customerRecordEdit?.kind==="reschedule"){
  changes.append(el("h2","Request new dates"),el("p","A changed request returns to Submitted. Admin must review and confirm it again.","meta"));const form=el("form");form.className="record-reschedule";
  if(b.booking_type==="GROOMING")form.append(bookingField("New appointment date and time (MYT)","record-appointment","datetime-local",recordLocal(b.grooming_start),()=>{}));else form.append(bookingField("New check-in date","record-checkin","date",b.boarding_start,()=>{}),bookingField("New checkout date","record-checkout","date",b.boarding_end,()=>{}));
  const submit=el("button","Submit reschedule request");submit.type="submit";form.append(submit,quiet("Keep current dates",()=>{customerRecordEdit=null;drawCustomerBookingDetail(data,valid);}));form.addEventListener("submit",event=>{event.preventDefault();let payload;if(b.booking_type==="GROOMING"){const value=$("record-appointment").value;if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)){recordFeedback("Choose a valid appointment date and time.");return;}payload={grooming_start:new Date(value+":00+08:00").toISOString()};}else{if($("record-checkout").value<=$("record-checkin").value){recordFeedback("Checkout must be after check-in.");return;}payload={boarding_start:$("record-checkin").value,boarding_end:$("record-checkout").value};}mutate("reschedule",payload);});changes.append(form);
 }else if(changeable){changes.append(button("Reschedule",()=>{customerRecordEdit={kind:"reschedule"};drawCustomerBookingDetail(data,valid);customerPanel.querySelector(".record-reschedule input").focus();}),quiet("Cancel booking",()=>{customerRecordEdit={kind:"cancel"};drawCustomerBookingDetail(data,valid);customerPanel.querySelector(".record-change button").focus();}));}
 if(changes.childElementCount)customerPanel.append(changes);
 const record=data.grooming_record||data.boarding_stay;if(record){customerPanel.append(el("h2",b.booking_type==="GROOMING"?"Service record":"Stay record"));const times=[];for(const [field,label]of [["started_at","Started"],["checked_in_at","Checked in"],["stay_started_at","Stay started"],["checked_out_at","Checked out"],["completed_at","Completed"]])if(record[field]&&!(field==="stay_started_at"&&record[field]===record.checked_in_at))times.push([label,recordTime(record[field])]);customerPanel.append(recordDefinition(times));if(data.grooming_record)customerPanel.append(el("h3","Service notes"),el("p",record.service_notes||"No service notes recorded.","notes"));}
 if(data.stay_notes){customerPanel.append(el("h2","Stay updates"));if(!data.stay_notes.length)customerPanel.append(el("p","No stay updates recorded.","meta"));for(const n of data.stay_notes){const note=el("section",undefined,"record-note");note.append(el("p",n.note,"notes"),el("p",recordTime(n.created_at),"meta"));customerPanel.append(note);}}
 customerPanel.append(el("h2","Booking history"));const history=el("ol",undefined,"record-timeline");
 const eventNames={BOOKING_SUBMITTED:"Request submitted",STATUS_CHANGED:"Booking status updated",BOOKING_RESCHEDULED:"Reschedule requested",BOOKING_CANCELLED:"Booking cancelled",STAFF_ASSIGNED:"Staff assigned",STAFF_REASSIGNED:"Staff assignment updated",ACCOMMODATION_ALLOCATED:"Accommodation allocated",ACCOMMODATION_REALLOCATED:"Accommodation updated",GROOMING_STARTED:"Grooming started",GROOMING_COMPLETED:"Grooming completed",BOARDING_CHECKED_IN:"Staying",BOARDING_STAY_STARTED:"Stay started",BOARDING_CHECKED_OUT:"Completed",BOARDING_COMPLETED:"Boarding completed",BOARDING_NOTE_ADDED:"Stay update added"};
 for(const event of data.history){const item=el("li");item.append(el("strong",eventNames[event.event_type]||human(event.event_type).replace(/^./,c=>c.toUpperCase())),el("p",recordTime(event.created_at),"meta"));if(event.old_status||event.new_status)item.append(el("p",[...new Set([event.old_status,event.new_status].filter(Boolean))].map(recordLabel).join(" → ")));for(const [key,title]of [["old_schedule","Previous dates"],["new_schedule","Recorded dates"]]){const schedule=event[key];if(schedule?.grooming_start)item.append(el("p",title+": "+recordTime(schedule.grooming_start),"meta"));else if(schedule?.boarding_start)item.append(el("p",title+": "+recordDate(schedule.boarding_start)+" → "+recordDate(schedule.boarding_end),"meta"));}history.append(item);}customerPanel.append(history);
 const metadata=el("details",undefined,"record-metadata");metadata.append(el("summary","Record details"),el("p","Booking reference: "+b.id,"meta"));for(const e of data.history)metadata.append(el("p",(eventNames[e.event_type]||human(e.event_type))+" · Account reference: "+e.actor_user_id+" · "+recordTime(e.created_at),"meta"));for(const n of data.stay_notes||[])metadata.append(el("p","Stay update account reference: "+n.actor_user_id+" · "+recordTime(n.created_at),"meta"));
 // The accepted scoped detail and legacy Customer view already expose retained allocation history.
 if(data.allocation_history?.length){const allocations=el("details");allocations.append(el("summary","Accommodation history"));for(const a of data.allocation_history)allocations.append(el("p",a.name+" · "+recordDate(a.starts_on)+" → "+recordDate(a.ends_on)+" · "+(a.released_at?"Released "+recordTime(a.released_at):"Reserved"),"meta"));metadata.append(allocations);}customerPanel.append(metadata);
}
function drawCustomerNotifications(data,valid){drawEventFeed(customerPanel,data,valid,false,customerNoticeOffset,async value=>{customerNoticeOffset=value;await refresh();});}
