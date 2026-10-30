const $ = (id) => document.getElementById(id);

function show(entry) {
  const s = $("status");
  if (entry?.error) {
    s.className = "err";
    s.textContent = entry.error;
  } else if (entry?.known) {
    s.className = "";
    const mins = Math.round((Date.now() - entry.at) / 60000);
    s.textContent = `Working. Knows ${entry.known.count} leads (updated ${mins ? `${mins} min ago` : "just now"}). Reload your Apollo tab to see the marks.`;
  }
}

function check(force) {
  $("status").className = "";
  $("status").textContent = "Checking… (the online CRM can take up to a minute to wake up)";
  chrome.runtime.sendMessage({ type: "getKnown", force }, show);
}

chrome.storage.local.get(["crm", "code", "cache"], (s) => {
  if (s.crm) $("crm").value = s.crm;
  if (s.code) $("code").value = s.code;
  if (s.cache) show(s.cache);
});

$("save").onclick = () => {
  chrome.storage.local.set({ crm: $("crm").value, code: $("code").value.trim(), cache: null }, () => check(true));
};
$("refresh").onclick = () => check(true);
