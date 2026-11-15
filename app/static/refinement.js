"use strict";
// Original outline icons and presentation hooks; no additional routes, requests or permissions.
const refinementPaths = {
 home:["M3 10 12 3l9 7","M5 9v12h5v-7h4v7h5V9"],
 book:["M5 5h14v16H5z","M8 3v4m8-4v4M5 10h14m-7 3v5m-2.5-2.5h5"],
 calendar:["M4 5h16v16H4z","M8 3v4m8-4v4M4 10h16m-12 4h3m3 0h3m-9 4h3"],
 bell:["M6 17h12l-2-3V9a4 4 0 0 0-8 0v5l-2 3Z","M10 21h4M12 3v2"],
 user:["M16 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0Z","M4 21v-2a8 8 0 0 1 16 0v2"],
 work:["M8 5V3h8v2M3 6h18v15H3z","M3 12h18m-11 0v3h4v-3"],
 staff:["M10 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm10 0a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z","M1 21v-2a6 6 0 0 1 12 0v2m1-7a6 6 0 0 1 9 5v2"],
 services:["M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z"],
 chart:["M3 3v18h18","M7 17v-5m5 5V7m5 10V4"],
 history:["M4 7a9 9 0 1 1-1 9","M4 3v5h5m3-2v6l4 2"],
 settings:["M4 6h16M4 12h16M4 18h16","M8 3v6m8 0v6M9 15v6"],
 grooming:["M8 7a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm0 10a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z","M7 9 21 21M7 15 21 3"],
 boarding:["M3 10 12 3l9 7","M5 9v12m14-12v12M7 17h10v4M7 13v8m0-7h4v3"],
 arrow:["M4 12h16m-6-6 6 6-6 6"]
};
function refinementIcon(name) {
 const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
 for(const [key,value] of Object.entries({viewBox:"0 0 24 24",fill:"none",stroke:"currentColor","stroke-linecap":"round","stroke-linejoin":"round","aria-hidden":"true",focusable:"false",class:"refinement-icon"}))svg.setAttribute(key,value);
 for(const d of refinementPaths[name]||refinementPaths.services){const path=document.createElementNS("http://www.w3.org/2000/svg","path");path.setAttribute("d",d);svg.append(path);}
 return svg;
}
function refinementDecorate(node,name) {
 if(node&&!node.querySelector(".refinement-icon"))node.prepend(refinementIcon(name));
}
function refinementEnhance() {
 document.body.dataset.role=user?.role?.toLowerCase()||"guest";
 const navigation={"nav-customer-home":"home","nav-customer-book":"book","nav-customer-bookings":"calendar","nav-customer-account":"user","nav-inbox":"bell","nav-staff-work":"work","nav-staff-account":"user","nav-admin-overview":"home","nav-admin-bookings":"calendar","nav-admin-boarding":"boarding","nav-admin-staff":"staff","nav-admin-services":"services","nav-admin-insights":"chart","nav-admin-history":"history","nav-admin-settings":"settings"};
 for(const [id,name] of Object.entries(navigation))refinementDecorate($(id),name);
 for(const heading of document.querySelectorAll(".booking-flow h2, .booking-flow h3")){const name=heading.textContent.trim();if(name==="Grooming"||name==="Boarding"){heading.classList.add("service-heading");refinementDecorate(heading,name.toLowerCase());}}
 for(const cue of document.querySelectorAll(".home-service-cue"))refinementDecorate(cue,cue.dataset.service);
 refinementDecorate($("home-book-service"),"arrow");
}
const preRefinementEnhance=productEnhance;
productEnhance=function(){preRefinementEnhance();refinementEnhance();};
refinementEnhance();
