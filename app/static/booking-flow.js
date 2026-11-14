"use strict";
// Ephemeral UI draft only. Existing APIs own eligibility, capacity, validation and creation.
function freshBookingDraft(){return {step:0,petId:"",serviceId:"",appointment:"",start:"",end:"",version:0,receipt:null,unknown:false};}
let bookingDraft=freshBookingDraft(), bookingChoices=null, bookingBusy=false;
function resetBookingFlow(){bookingDraft=freshBookingDraft();bookingChoices=null;bookingBusy=false;}
function bookingValid(draft,revision,account){return draft===bookingDraft&&revision===viewRevision&&user?.id===account&&user?.role==="CUSTOMER"&&activePage==="customer-book";}
function bookingErrorText(error){
 const detail=String(error.message||"");
 if(error.status===404)return "The selected pet is no longer available. Return to Pet & Service and refresh your choices.";
 if(/Selected service is not active|configure Grooming duration/i.test(detail))return "This service is no longer available as selected. Return to Pet & Service and choose again.";
 if(error.status===409){if(/accommodation.*capacity/i.test(detail))return "No accommodation has space throughout these dates. Choose another stay.";if(/available Staff|conflicting assignment/i.test(detail))return "No Staff member is available for the full appointment. Choose another date or time.";return "Availability or booking details changed. Check your dates again before submitting.";}
 if(/past|future/i.test(detail))return "Choose an appointment or check-in date that is not in the past. Grooming appointments must be in the future.";
 if(error.status===422)return "Check the pet, service and dates. Checkout must be after check-in, and the appointment must be a valid date and time.";
 if(!error.status)return "We couldn’t reach PetOps. Check your connection and try again.";
 return "We couldn’t complete this request. Please refresh your choices and try again.";
}
function bookingNotice(text){let target=$("booking-feedback");if(!target)return;target.textContent=text;target.hidden=!text;if(text){target.focus();}}
function bookingField(label,id,type,value,onInput){const wrapper=el("label",label),input=el("input");input.id=id;input.type=type;input.required=true;input.value=value;input.addEventListener("input",()=>onInput(input.value));wrapper.append(input);return wrapper;}
function bookingSchedule(draft,service){
 if(service.service_type==="GROOMING"){
  if(!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(draft.appointment))throw new Error("Choose a valid appointment date and time.");
  const instant=new Date(draft.appointment+":00+08:00");if(!Number.isFinite(instant.getTime()))throw new Error("Choose a valid appointment date and time.");
  return {service_id:service.id,grooming_start:instant.toISOString()};
 }
 if(!draft.start||!draft.end||draft.end<=draft.start)throw new Error("Choose both stay dates, with checkout after check-in.");
 return {service_id:service.id,boarding_start:draft.start,boarding_end:draft.end};
}
function bookingSummary(draft,pet,service){const dl=el("dl",undefined,"booking-summary");const rows=[["Pet",pet.name],["Service",service.name],["Service type",service.service_type==="GROOMING"?"Grooming":"Boarding"]];
 if(service.service_type==="GROOMING"){rows.push(["Preferred time",new Intl.DateTimeFormat("en-MY",{timeZone:"Asia/Kuala_Lumpur",dateStyle:"full",timeStyle:"short"}).format(new Date(draft.appointment+":00+08:00"))+" MYT"],["Duration",service.duration_minutes+" minutes"]);}else rows.push(["Check-in date",draft.start],["Checkout date",draft.end]);
 for(const [label,value] of rows)dl.append(el("dt",label),el("dd",value));return dl;
}
function bookingSteps(step){const list=el("ol",undefined,"booking-steps");list.setAttribute("aria-label","Booking progress");for(const [i,title] of ["Pet & Service","Dates","Review"].entries()){const li=el("li");li.append(el("span",String(i+1),"step-number"),el("span",title));if(i===step)li.setAttribute("aria-current","step");list.append(li);}return list;}
async function renderBookingFlow(revision){
 const draft=bookingDraft,account=user.id;const valid=()=>bookingValid(draft,revision,account);
 customerPanel.setAttribute("aria-busy","true");const load=el("p","Loading your pets and services…","meta");load.setAttribute("role","status");customerPanel.replaceChildren(load);
 try{
  const [allPets,services]=await Promise.all([api("/pets"),api("/services")]);if(!valid())return;const pets=allPets.filter(p=>p.is_active!==false);bookingChoices={pets,services};
  const oldService=services.find(s=>s.id===draft.serviceId);
  if(!draft.receipt&&((draft.petId&&!pets.some(p=>p.id===draft.petId))||(draft.serviceId&&!oldService))){draft.petId="";draft.serviceId="";draft.step=0;draft.version++;}
  if(pets.length===1&&!draft.petId)draft.petId=pets[0].id;if(services.length===1&&!draft.serviceId)draft.serviceId=services[0].id;
  drawBookingFlow(draft,valid);
 }catch(error){if(!valid())return;if(error.status===401){signedOut();message("Your session expired. Sign in again to start a new request.",true);return;}customerPanel.replaceChildren(customerHeading("Booking is unavailable","Your pets and services could not be loaded."),quiet("Try again",()=>refresh()));message(bookingErrorText(error),true);
 }finally{if(valid())customerPanel.removeAttribute("aria-busy");}
}
function drawBookingFlow(draft,valid){
 const {pets,services}=bookingChoices,pet=pets.find(p=>p.id===draft.petId),service=services.find(s=>s.id===draft.serviceId);
 const context=draft.receipt?"Admin will review your request before confirmation.":draft.step===0?"Choose a pet and a service. Dates come next.":draft.step===1?"Choose preferred dates. Admin confirms the request after preparation.":"Check the details before sending your request.";
 customerPanel.replaceChildren(customerHeading(draft.receipt?"Booking request submitted":"Book a service",context));
 const area=el("div",undefined,"booking-flow");customerPanel.append(area);
 const feedback=el("p",undefined,"booking-feedback");feedback.id="booking-feedback";feedback.hidden=true;feedback.tabIndex=-1;feedback.setAttribute("role","alert");area.append(feedback);
 if(draft.receipt){const status=draft.receipt.status;area.append(el("span",status==="SUBMITTED"?"Requested":human(status),"status-badge waiting"),bookingSummary(draft,draft.receipt.pet,draft.receipt.service),el("p","This is a booking request, not a confirmed visit.","meta"),button("My Bookings",async()=>{const receipt=draft.receipt;serviceKind=receipt.booking_type;if(typeof customerRecordFilter!=="undefined"){customerRecordFilter="current";customerRecordType="ALL";}await customerGo("bookings");}),quiet("Home",()=>customerGo("home")));return;}
 if(draft.unknown){area.append(el("h2","Check My Bookings before trying again"),el("p","We couldn’t confirm whether your request was saved. Open My Bookings and check before starting another request."),button("Check My Bookings",async()=>{serviceKind=service?.service_type||"GROOMING";if(typeof customerRecordFilter!=="undefined"){customerRecordFilter="all";customerRecordType="ALL";}await customerGo("bookings");}));return;}
 area.prepend(bookingSteps(draft.step));
 const changed=()=>{draft.version++;feedback.textContent="";feedback.hidden=true;};
 const step=async next=>{if(bookingBusy)return;draft.step=next;draft.version++;drawBookingFlow(draft,valid);const heading=customerPanel.querySelector("h1");heading.tabIndex=-1;heading.focus();};
 if(draft.step===0){
  const petGroup=el("fieldset"),petLegend=el("legend","Who are we booking for?");petGroup.append(petLegend);area.append(petGroup);
  if(!pets.length)petGroup.append(el("p","Add your pet’s name before booking a service.","meta"),button("Add pet",async()=>{await customerGo("pets");petView={kind:"add"};await refresh();}));
  else if(pets.length===1){const summary=el("div",undefined,"booking-single");summary.append(petAvatar(pets[0].name),el("strong",pets[0].name),el("span","Selected pet","meta"));petGroup.append(summary);}
  else {const choices=el("div",undefined,"booking-pets");for(const p of pets){const label=el("label",undefined,"booking-choice pet-choice"),radio=el("input");radio.type="radio";radio.name="booking-pet";radio.value=p.id;radio.checked=p.id===draft.petId;radio.addEventListener("change",()=>{draft.petId=p.id;changed();});label.append(radio,petAvatar(p.name),el("span",p.name));choices.append(label);}petGroup.append(choices);}
  const group=el("fieldset");group.append(el("legend","Choose a service"));area.append(group);
  if(!services.length)group.append(el("p","No services are available for booking right now. Please try again later.","meta"),quiet("Refresh services",()=>refresh()));
  else if(services.length===1){const s=services[0];group.append(el("div",s.name+" · "+(s.service_type==="GROOMING"?"Grooming · "+s.duration_minutes+" minutes":"Boarding"),"booking-single"));}
  else for(const kind of ["GROOMING","BOARDING"]){const matching=services.filter(s=>s.service_type===kind).sort((a,b)=>a.display_order-b.display_order||a.name.localeCompare(b.name));if(!matching.length)continue;group.append(el("h2",kind==="GROOMING"?"Grooming":"Boarding"));const choices=el("div",undefined,"booking-services");for(const s of matching){const label=el("label",undefined,"booking-choice service-choice"),radio=el("input");radio.type="radio";radio.name="booking-service";radio.value=s.id;radio.checked=s.id===draft.serviceId;label.classList.toggle("selected",radio.checked);radio.addEventListener("change",()=>{draft.serviceId=s.id;changed();for(const c of group.querySelectorAll(".service-choice"))c.classList.toggle("selected",c.querySelector("input").checked);});label.append(radio,el("strong",s.name),el("span",kind==="GROOMING"?s.duration_minutes+" minutes":"Choose stay dates next","meta"));choices.append(label);}group.append(choices);}
  const next=button("Continue",()=>{if(!draft.petId){bookingNotice("Choose a pet before continuing.");return;}if(!draft.serviceId){bookingNotice("Choose a service before continuing.");return;}return step(1);});next.disabled=!pets.length||!services.length;area.append(next);
 }else if(draft.step===1){
  if(!pet||!service){draft.step=0;drawBookingFlow(draft,valid);return;}
  area.append(el("h2","Choose your dates"),el("p",pet.name+" · "+service.name,"meta"));
  const form=el("form");form.className="booking-dates";
  if(service.service_type==="GROOMING"){form.append(bookingField("Preferred date and time (MYT)","booking-appointment","datetime-local",draft.appointment,value=>{draft.appointment=value;changed();}),el("p",service.duration_minutes+"-minute appointment. Times use Malaysia time (MYT).","meta"));}
  else form.append(bookingField("Check-in date","booking-checkin","date",draft.start,value=>{draft.start=value;changed();}),bookingField("Checkout date","booking-checkout","date",draft.end,value=>{draft.end=value;changed();}),el("p","Accommodation is reserved until the checkout date. Availability is rechecked when you submit.","meta"));
  const next=el("button","Check Availability & Review");next.type="submit";form.append(quiet("Back",()=>step(0)),next);area.append(form);
  form.addEventListener("submit",async event=>{event.preventDefault();if(bookingBusy)return;let schedule;try{schedule=bookingSchedule(draft,service);}catch(error){bookingNotice(error.message);return;}
   const version=draft.version;bookingBusy=true;next.disabled=true;next.textContent="Checking availability…";feedback.hidden=true;
   try{const result=await api("/availability","POST",schedule);if(!valid()||draft.version!==version)return;if(!result.available){bookingNotice(service.service_type==="GROOMING"?"No Staff member is available for the full appointment. Choose another date or time.":"No accommodation has space throughout these dates. Choose another stay.");return;}draft.step=2;drawBookingFlow(draft,valid);const title=customerPanel.querySelector("h1");title.tabIndex=-1;title.focus();
   }catch(error){if(valid()&&draft.version===version){if(error.status===401){signedOut();message("Your session expired. Sign in again to start a new request.",true);}else bookingNotice(bookingErrorText(error));}}
   finally{if(draft===bookingDraft)bookingBusy=false;if(next.isConnected){next.disabled=false;next.textContent="Check Availability & Review";}}
  });
 }else{
  if(!pet||!service){draft.step=0;drawBookingFlow(draft,valid);return;}
  area.append(el("h2","Review your request"),bookingSummary(draft,pet,service),el("p","Your booking request will be reviewed before confirmation. Availability is checked again when you submit.","booking-explanation"));
  const controls=el("div",undefined,"booking-actions"),submit=button("Submit Booking",async()=>{
   if(bookingBusy)return;bookingBusy=true;submit.disabled=true;submit.textContent="Submitting…";const schedule=bookingSchedule(draft,service);
   try{const result=await api("/bookings","POST",{...schedule,pet_id:draft.petId});if(!valid())return;draft.receipt={...result,pet:{...pet},service:{...service}};drawBookingFlow(draft,valid);
   }catch(error){if(!valid())return;if(error.status===401){signedOut();message("Your session expired. Sign in again and check My Bookings before retrying.",true);}else if(!error.status||error.status>=500){draft.unknown=true;drawBookingFlow(draft,valid);}else{draft.step=1;drawBookingFlow(draft,valid);bookingNotice(bookingErrorText(error));}}
   finally{if(draft===bookingDraft)bookingBusy=false;}
  });controls.append(quiet("Back to Dates",()=>step(1)),quiet("Change Pet or Service",()=>step(0)),submit);area.append(controls);
 }
 area.append(el("p","","booking-draft-note"));
}
