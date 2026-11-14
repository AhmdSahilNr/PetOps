"use strict";
// Customer presentation only. All records and mutations use existing scoped APIs.
let customerAccount=null, customerIntent="bookings", petView=null, profileEditing=false;
const customerPanel=el("section");customerPanel.id="customer-page";customerPanel.hidden=true;$("workspace").append(customerPanel);
const customerLinks=[];
for(const [key,label] of [["home","Home"],["book","Book a service"],["bookings","My Bookings"],["account","My Account"]]){
 const b=button(label,()=>customerGo(key));b.id="nav-customer-"+key; b.hidden=true;customerLinks.push(b);
 shellNav.insertBefore(b,key==="profile"?$("refresh"):$("nav-grooming"));
}
function configureCustomerNavigation(){if(user.role==="CUSTOMER"&&customerAccount!==user.id){customerAccount=user.id;activePage="customer-home";petView=null;profileEditing=false;}if(user.role!=="CUSTOMER")customerAccount=null;}
function clearCustomerView(){customerAccount=null;petView=null;profileEditing=false;customerPanel.replaceChildren();customerPanel.hidden=true;for(const b of customerLinks)b.hidden=true;if(typeof resetBookingFlow==="function")resetBookingFlow();if(typeof resetCustomerRecords==="function")resetCustomerRecords();}
function syncCustomerShell(){const own=user?.role==="CUSTOMER";for(const b of customerLinks){b.hidden=!own;b.removeAttribute("aria-current");}if(!own){$("nav-grooming").hidden=false;$("nav-boarding").hidden=false;return;}
 const key=activePage.startsWith("customer-")?activePage.slice(9):activePage==="work"?customerIntent:null;
 if(key==="notifications")$("nav-inbox").setAttribute("aria-current","page");else if(key)$("nav-customer-"+(["pets","profile"].includes(key)?"account":key==="detail"?"bookings":key))?.setAttribute("aria-current","page");
 for(const kind of ["grooming","boarding"]){$("nav-"+kind).hidden=activePage!=="work";$("nav-"+kind).textContent=kind==="grooming"?"Grooming":"Boarding";}
}
function prepareCustomerView(){customerPanel.hidden=user.role!=="CUSTOMER"||!activePage.startsWith("customer-");if(customerPanel.hidden)customerPanel.replaceChildren();
 if(user.role!=="CUSTOMER")return;
 if(activePage!=="customer-book"&&typeof resetBookingFlow==="function")resetBookingFlow();
 // The existing forms stay attached for legacy booking refresh logic, but editing has dedicated views.
 $("profile").parentElement.hidden=true;
 if(activePage==="work"){if(selected)customerIntent="bookings";$("customer").hidden=customerIntent!=="book";$("work-section").hidden=customerIntent==="book";}
}
async function customerGo(key){if(key==="account")key="profile";petView=null;profileEditing=false;selected=null;message("");
 if(key!=="book"&&typeof resetBookingFlow==="function")resetBookingFlow();
 if(typeof resetCustomerRecordEdit==="function")resetCustomerRecordEdit();
 activePage="customer-"+key;
 await refresh();shellMain.focus();
}
function quiet(label,fn){const b=button(label,fn);b.classList.add("secondary");return b;}
function customerName(value,label){if(!value.trim())throw new Error("Enter a "+label+".");return value;}
function customerHeading(title,context,actionButton){const h=el("div",undefined,"customer-heading"),text=el("div");text.append(el("h1",title));if(context)text.append(el("p",context,"meta"));h.append(text);if(actionButton)h.append(actionButton);return h;}
function petAvatar(name){const a=el("span",Array.from(name.trim())[0]?.toLocaleUpperCase()||"·","pet-avatar");a.setAttribute("aria-hidden","true");return a;}
function petRow(p,actions){const row=el("div",undefined,"pet-row"),name=el("strong",p.name);row.append(petAvatar(p.name),name);if(p.is_active===false)row.append(el("span","Archived","status-badge"));const controls=el("div",undefined,"row-actions");controls.append(...actions);row.append(controls);return row;}
function customerStatus(status){const labels={SUBMITTED:"Requested",CONFIRMED:"Confirmed",IN_PROGRESS:"In progress",CHECKED_IN:"Staying",STAYING:"Staying",CHECKED_OUT:"Completed",COMPLETED:"Completed",CANCELLED:"Cancelled",REJECTED:"Rejected"};return el("span",labels[status]||human(status),"status-badge status-"+status.toLowerCase()+" "+(status==="SUBMITTED"?"waiting":status==="CONFIRMED"?"positive":["IN_PROGRESS","CHECKED_IN","STAYING"].includes(status)?"active":""));}
function bookingDate(b){return b.booking_type==="GROOMING"?new Intl.DateTimeFormat("en-MY",{timeZone:"Asia/Kuala_Lumpur",dateStyle:"full",timeStyle:"short"}).format(new Date(b.grooming_start))+" MYT":b.boarding_start+" → "+b.boarding_end+" · check-in to checkout";}
async function openCustomerBooking(b){message("");if(typeof resetCustomerRecordEdit==="function")resetCustomerRecordEdit();activePage="customer-detail";serviceKind=b.booking_type;selected=b.id;await refresh();shellMain.focus();}
async function renderCustomerPage(revision){const account=user.id,page=activePage;const valid=()=>revision===viewRevision&&user?.id===account&&user.role==="CUSTOMER"&&activePage===page;
 if(page==="customer-book"){await renderBookingFlow(revision);return;}
 if(["customer-bookings","customer-detail","customer-notifications"].includes(page)){await renderCustomerRecords(revision);return;}
 customerPanel.setAttribute("aria-busy","true");const loading=el("p","Loading your information…","meta");loading.setAttribute("role","status");customerPanel.replaceChildren(loading);
 try{if(page==="customer-home"){
 const [profile,pets,grooming,boarding]=await Promise.all([api("/customer/profile"),api("/pets"),api("/grooming/bookings"),api("/boarding/bookings")]);if(!valid())return;
 customerPanel.replaceChildren(customerHeading("Hello, "+profile.display_name,"",button("Book a service",()=>customerGo("book"))));
 const rows=[...grooming,...boarding],active=rows.filter(b=>["IN_PROGRESS","CHECKED_IN","STAYING","CHECKED_OUT"].includes(b.status));
 const upcoming=rows.filter(b=>b.status==="CONFIRMED"&&(b.booking_type==="GROOMING"?new Date(b.grooming_start)>=new Date():b.boarding_end>businessDate()));
 const time=b=>b.grooming_start||b.boarding_start;const ranked=[...active.sort((a,b)=>time(a).localeCompare(time(b))),...upcoming.sort((a,b)=>time(a).localeCompare(time(b)))];
 if(ranked.length){const b=ranked[0],lead=el("section",undefined,"customer-lead");lead.append(el("p",active.includes(b)?"CURRENT BOOKING":"NEXT BOOKING","eyebrow"),customerStatus(b.status));const name=el("div",undefined,"lead-pet");name.append(petAvatar(b.pet_name),el("h2",b.pet_name));lead.append(name,el("h3",b.service_name),el("p",bookingDate(b)),button("View booking",()=>openCustomerBooking(b)));if(ranked.length>1)lead.append(quiet("View all bookings",()=>customerGo("bookings")));customerPanel.append(lead);
 }else{const empty=el("section",undefined,"customer-lead");empty.append(el("h2",!pets.length?"No pets yet":!rows.length?"No bookings yet":"No upcoming bookings"),el("p",!pets.length?"Add a pet to book their first visit.":"Book grooming or a boarding stay."),button(!pets.length?"Add pet":"Book a service",async()=>{if(!pets.length){await customerGo("pets");petView={kind:"add"};await refresh();}else await customerGo("book");}));customerPanel.append(empty);}
 const waiting=rows.filter(b=>b.status==="SUBMITTED"),grid=el("div",undefined,"customer-home-grid");if(waiting.length){const section=el("section");section.append(el("h2","Awaiting confirmation"),el("p","We’ll notify you when a request is confirmed.","meta"));for(const b of waiting.slice(0,3)){const row=el("div",undefined,"request-row");row.append(el("strong",b.pet_name),el("p",b.service_name+" · "+bookingDate(b),"meta"),quiet("View request",()=>openCustomerBooking(b)));section.append(row);}if(waiting.length>3)section.append(quiet("View requests",()=>customerGo("bookings")));grid.append(section);}
 if(pets.length){const petSummary=el("section");petSummary.append(el("h2","Your pets"));for(const p of pets.slice(0,4))petSummary.append(petRow(p,[]));petSummary.append(quiet("My Pets",()=>customerGo("pets")));grid.append(petSummary);}if(grid.childElementCount)customerPanel.append(grid);
 }else if(page==="customer-pets"){
 const pets=await api("/pets");if(!valid())return;customerPanel.replaceChildren(customerHeading("My Pets","",button("Add pet",async()=>{petView={kind:"add"};await refresh();})));
 if(petView){const pet=pets.find(p=>p.id===petView.id);if(petView.kind!=="add"&&!pet){petView=null;throw new Error("This pet is no longer available. Refresh your pet list.");}
 if(petView.kind==="view"){const detail=el("section",undefined,"customer-readable");detail.append(petAvatar(pet.name),el("h2",pet.name),quiet("Edit pet",async()=>{petView={kind:"edit",id:pet.id};await refresh();}),quiet("Back to My Pets",async()=>{petView=null;await refresh();}));customerPanel.append(detail);
 }else{const editing=petView.kind==="edit",form=operationForm(editing?"Edit pet":"Add pet",[{label:"Pet name",name:"name",value:pet?.name||"",required:true,maxLength:120}],editing?"Save changes":"Add pet",async data=>{
 data.name=customerName(data.name,"pet name");await api(editing?`/pets/${pet.id}`:"/pets",editing?"PUT":"POST",data);if(!valid())return;petView=null;await refresh();message(editing?"Pet updated.":"Pet added.");});form.classList.add("customer-edit");form.append(quiet("Cancel",async()=>{petView=null;await refresh();}));if(editing&&pet.is_active!==false){form.append(el("p","Pets with booking history cannot be deleted.","meta"),quiet("Archive pet",async()=>{if(!window.confirm("Archive this pet? Existing bookings and history are kept."))return;await api(`/pets/${pet.id}/archive`,"POST",{});if(!valid())return;petView=null;await refresh();message("Pet archived.");}));}customerPanel.append(form);form.querySelector("input").focus();}
 }else{if(!pets.length)customerPanel.append(el("p","No pets added yet. Add a pet to start booking.","meta"));for(const p of pets)customerPanel.append(petRow(p,[quiet("View",async()=>{petView={kind:"view",id:p.id};await refresh();}),quiet("Edit",async()=>{petView={kind:"edit",id:p.id};await refresh();})]));}
 }else if(page==="customer-profile"){
 const profile=await api("/customer/profile");if(!valid())return;customerPanel.replaceChildren(customerHeading("Profile",""));
 if(profileEditing){const form=operationForm("Edit profile",[{label:"Display name",name:"display_name",value:profile.display_name,required:true,maxLength:120}],"Save changes",async data=>{data.display_name=customerName(data.display_name,"display name");await api("/customer/profile","PUT",data);if(!valid())return;profileEditing=false;await refresh();message("Profile saved.");});form.classList.add("customer-edit");form.append(quiet("Cancel",async()=>{profileEditing=false;await refresh();}));customerPanel.append(form);form.querySelector("input").focus();
 }else{const dl=el("dl",undefined,"profile-summary");for(const [label,value]of [["Display name",profile.display_name],["Email",profile.email]])dl.append(el("dt",label),el("dd",value));customerPanel.append(dl,button("Edit profile",async()=>{profileEditing=true;await refresh();}));}
 }
 }catch(error){if(valid()){customerPanel.replaceChildren(customerHeading("Your information is unavailable","Please try loading this page again."),quiet("Try again",()=>refresh()));message(error.message,true);}}
 finally{if(valid()){customerPanel.removeAttribute("aria-busy");if(["customer-pets","customer-profile"].includes(page)){const oldHeading=customerPanel.querySelector("h1");if(oldHeading)oldHeading.replaceWith(el("h2",oldHeading.textContent));const tabs=el("div",undefined,"record-filters");for(const [key,title]of [["profile","Profile"],["pets","My Pets"]]){const b=quiet(title,()=>customerGo(key));b.setAttribute("aria-pressed",String(page==="customer-"+key));tabs.append(b);}customerPanel.prepend(customerHeading("My Account"),tabs);}}}
}
