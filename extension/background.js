// Downloads the CRM's known-leads list and keeps a cached copy, so Apollo pages
// can be checked instantly. The list is refreshed when older than 5 minutes.

const DEFAULT_CRM = "https://clinirev-outreach.onrender.com";
const MAX_AGE_MS = 5 * 60 * 1000;

async function settings() {
  const s = await chrome.storage.local.get(["crm", "code"]);
  return { crm: s.crm || DEFAULT_CRM, code: s.code || "" };
}

async function fetchKnown() {
  const { crm, code } = await settings();
  if (!code) throw new Error("Enter the extension code first (click the extension icon).");
  const res = await fetch(`${crm}/api/known`, { headers: { "X-Extension-Token": code } });
  if (res.status === 401) throw new Error("Wrong extension code.");
  if (!res.ok) throw new Error(`CRM answered ${res.status}. If it was asleep, try again in a minute.`);
  const known = await res.json();
  const entry = { known, at: Date.now(), error: "" };
  await chrome.storage.local.set({ cache: entry });
  return entry;
}

async function getKnown(force) {
  const { cache } = await chrome.storage.local.get("cache");
  if (!force && cache && cache.known && Date.now() - cache.at < MAX_AGE_MS) return cache;
  try {
    return await fetchKnown();
  } catch (e) {
    // Keep using the last good list if the CRM is unreachable (e.g. waking up).
    const entry = { ...(cache || {}), error: e.message };
    await chrome.storage.local.set({ cache: entry });
    return entry;
  }
}

chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg.type === "getKnown") {
    getKnown(Boolean(msg.force)).then(reply);
    return true; // reply asynchronously
  }
});
