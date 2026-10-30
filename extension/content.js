// Runs on app.apollo.io. Finds people on the page and marks the ones already in
// the CRM: by LinkedIn profile (exact), email if visible (exact), or name +
// company (strong), or name only (a softer "check" warning).

let known = null;
let sets = null;

// Must match the server's normalisation in backend/app/main.py.
function linkedinSlug(url) {
  url = (url || "").toLowerCase().split("?")[0].replace(/\/+$/, "");
  const i = url.indexOf("/in/");
  return i >= 0 ? url.slice(i + 4) : "";
}
function nameKey(text) {
  return (text || "")
    .toLowerCase()
    .replace(/\b(dr|md|do|mba|phd|faad|mph|pa-c|np)\b\.?/g, " ")
    .replace(/[^a-z ]/g, " ")
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}
const STOP = new Set(["the", "and", "llc", "pllc", "inc", "of", "group", "center", "centre",
  "medical", "associates", "practice", "clinic", "partners", "health", "care", "md"]);
function companyTokens(text) {
  return new Set(
    (text || "").toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/)
      .filter((w) => w.length >= 3 && !STOP.has(w))
  );
}

function buildSets(k) {
  return {
    linkedin: new Set(k.linkedin || []),
    emails: new Set(k.emails || []),
    names: k.names || {},
  };
}

// The smallest element around a person that holds their row of details.
function rowOf(el) {
  return (
    el.closest('[role="row"], tr, [data-cy-row], [class*="TableRow"], [class*="tableRow"], li') ||
    el.parentElement?.parentElement?.parentElement ||
    el
  );
}

function unmark(row) {
  row.querySelectorAll(".clinirev-badge").forEach((b) => b.remove());
  row.classList.remove("clinirev-dup", "clinirev-maybe");
  delete row.dataset.clinirev;
  delete row.dataset.clinirevFor;
}

function badge(row, anchor, kind, why) {
  const has = row.querySelector(`.clinirev-badge.${kind}`);
  // Already marked (a "dup" mark also wins over a softer "maybe").
  if (has || (row.dataset.clinirev === "dup" && kind === "maybe")) return;
  unmark(row);
  row.dataset.clinirev = kind;
  row.dataset.clinirevFor = anchor?.getAttribute("href") || "";
  row.classList.add(kind === "dup" ? "clinirev-dup" : "clinirev-maybe");
  const b = document.createElement("span");
  b.className = `clinirev-badge ${kind}`;
  b.textContent = kind === "dup" ? "ALREADY IN CRM" : "SAME NAME? CHECK";
  b.title = why;
  (anchor || row).insertAdjacentElement("afterend", b);
}

function scan() {
  if (!sets) return;
  // Apollo reuses rows while scrolling: drop marks whose person has left the row.
  document.querySelectorAll("[data-clinirev]").forEach((row) => {
    const href = row.dataset.clinirevFor;
    const stillThere = href && [...row.querySelectorAll("a")].some((a) => a.getAttribute("href") === href);
    if (!stillThere) unmark(row);
  });
  // 1. LinkedIn profile links: exact match.
  document.querySelectorAll('a[href*="linkedin.com/in/"]').forEach((a) => {
    if (sets.linkedin.has(linkedinSlug(a.href))) badge(rowOf(a), a, "dup", "Same LinkedIn profile as a lead in the CRM");
  });
  // 2. Person name links (Apollo links each name to its person page).
  document.querySelectorAll('a[href*="/people/"], a[href*="/contacts/"]').forEach((a) => {
    const key = nameKey(a.textContent);
    if (!key || key.split(" ").length < 2) return;
    const companies = sets.names[key];
    if (!companies) return;
    const row = rowOf(a);
    const rowWords = companyTokens(row.textContent);
    const sameCompany = companies.some((c) => [...companyTokens(c)].some((w) => rowWords.has(w)));
    if (sameCompany) badge(row, a, "dup", `"${a.textContent.trim()}" at the same company is already in the CRM`);
    else badge(row, a, "maybe", `Someone named "${a.textContent.trim()}" is in the CRM (${companies.join(", ")}). Check before exporting.`);
  });
  // 3. Any visible email address (after a reveal).
  document.querySelectorAll('a[href^="mailto:"]').forEach((a) => {
    const email = a.getAttribute("href").slice(7).toLowerCase();
    if (sets.emails.has(email)) badge(rowOf(a), a, "dup", "This email is already in the CRM");
  });
  updateBanner();
}

function updateBanner(error) {
  let bar = document.getElementById("clinirev-banner");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "clinirev-banner";
    document.body.appendChild(bar);
  }
  const dups = document.querySelectorAll('[data-clinirev="dup"]').length;
  const maybes = document.querySelectorAll('[data-clinirev="maybe"]').length;
  bar.className = error ? "error" : dups ? "has-dups" : "";
  bar.textContent = error
    ? `Clinirev: ${error}`
    : `Clinirev: ${dups} already in CRM${maybes ? `, ${maybes} to check` : ""} on this page · knows ${known?.count ?? 0} leads`;
}

let timer = null;
function scheduleScan() {
  clearTimeout(timer);
  timer = setTimeout(scan, 400);
}

function load(force) {
  chrome.runtime.sendMessage({ type: "getKnown", force }, (entry) => {
    if (entry?.known) {
      known = entry.known;
      sets = buildSets(known);
      scan();
    }
    if (entry?.error) updateBanner(entry.error);
  });
}

// Apollo is a single-page app: rows appear and change without page loads.
new MutationObserver(scheduleScan).observe(document.body, { childList: true, subtree: true });
load(false);
setInterval(() => load(false), 5 * 60 * 1000);
