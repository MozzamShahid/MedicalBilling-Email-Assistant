import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api.js";
import ImportDialog from "./ImportDialog.jsx";
import LeadDrawer from "./LeadDrawer.jsx";

export const STATUS_LABELS = {
  new: "New",
  researching: "Researching…",
  drafted: "Ready to send",
  sent: "Email 1 sent",
  follow_up_1: "Follow-up 1 sent",
  follow_up_2: "Follow-up 2 sent",
  replied: "Replied",
  meeting: "Meeting booked",
  won: "Won",
  not_interested: "Not interested",
  bounced: "Bounced",
  error: "Error",
};

const VIEWS = {
  all: { label: "All", match: () => true },
  due: { label: "Follow-ups due", match: (l) => isDue(l) },
  todo: { label: "To research", match: (l) => ["new", "researching", "error"].includes(l.status) },
  ready: { label: "Ready to send", match: (l) => l.status === "drafted" },
  sequence: { label: "In sequence", match: (l) => ["sent", "follow_up_1", "follow_up_2"].includes(l.status) },
  engaged: { label: "Replied / meeting", match: (l) => ["replied", "meeting", "won"].includes(l.status) },
  closed: { label: "Closed", match: (l) => ["not_interested", "bounced"].includes(l.status) },
};

const today = () => new Date().toISOString().slice(0, 10);
export const isDue = (l) =>
  ["sent", "follow_up_1"].includes(l.status) && l.next_follow_up_at && l.next_follow_up_at <= today();

export const fullName = (l) => `${l.first_name || ""} ${l.last_name || ""}`.trim() || "(no name)";

export const NEXT_SEND = {
  new: null,
  drafted: "Mark email 1 sent",
  sent: "Mark follow-up 1 sent",
  follow_up_1: "Mark follow-up 2 sent",
};

export default function App() {
  const [leads, setLeads] = useState([]);
  const [view, setView] = useState("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(new Set());
  const [openId, setOpenId] = useState(null);
  const [showImport, setShowImport] = useState(false);
  const [withResearch, setWithResearch] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(() => api.leads().then(setLeads).catch((e) => setError(e.message)), []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Poll while the crew is working on something.
  const busy = leads.some((l) => l.status === "researching");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [busy, refresh]);

  const counts = useMemo(
    () => Object.fromEntries(Object.entries(VIEWS).map(([k, v]) => [k, leads.filter(v.match).length])),
    [leads]
  );

  const shown = useMemo(() => {
    const q = search.toLowerCase();
    return leads
      .filter(VIEWS[view].match)
      .filter((l) =>
        !q ||
        [l.first_name, l.last_name, l.company, l.email, l.city, l.title].join(" ").toLowerCase().includes(q)
      );
  }, [leads, view, search]);

  const act = async (fn) => {
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    }
    refresh();
  };

  const toggle = (id) => {
    const next = new Set(selected);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelected(next);
  };
  const allShownSelected = shown.length > 0 && shown.every((l) => selected.has(l.id));
  const toggleAll = () => setSelected(allShownSelected ? new Set() : new Set(shown.map((l) => l.id)));

  const selectedIds = [...selected];
  const exportIds = selectedIds.length ? selectedIds : shown.filter((l) => l.body).map((l) => l.id);

  return (
    <div className="app">
      <header>
        <h1>Outreach CRM</h1>
        <div className="stats">
          <Stat label="Leads" value={leads.length} />
          <Stat label="To research" value={counts.todo} />
          <Stat label="Ready to send" value={counts.ready} />
          <Stat label="In sequence" value={counts.sequence} />
          <Stat label="Follow-ups due" value={counts.due} alert={counts.due > 0} />
          <Stat label="Replied / meeting" value={counts.engaged} good />
        </div>
      </header>

      <div className="toolbar">
        <button className="primary" onClick={() => setShowImport(true)}>+ Import leads</button>
        <button
          onClick={() => act(() => api.run(selectedIds.length ? selectedIds : null))}
          title="Research leads and draft emails. With nothing selected, runs every New / Error lead."
        >
          {selectedIds.length ? `Research ${selectedIds.length} selected` : "Research all new"}
        </button>
        <span className="spacer" />
        <label className="check">
          <input type="checkbox" checked={withResearch} onChange={(e) => setWithResearch(e.target.checked)} />
          include research
        </label>
        <a className={`btn ${exportIds.length ? "" : "disabled"}`} href={api.exportUrl("docx", exportIds, withResearch)}>
          Export DOCX
        </a>
        <a className={`btn ${exportIds.length ? "" : "disabled"}`} href={api.exportUrl("pdf", exportIds, withResearch)}>
          Export PDF
        </a>
      </div>

      <div className="filters">
        {Object.entries(VIEWS).map(([k, v]) => (
          <button key={k} className={`tab ${view === k ? "active" : ""}`} onClick={() => setView(k)}>
            {v.label} <span className="count">{counts[k]}</span>
          </button>
        ))}
        <input className="search" placeholder="Search name, company, city…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </div>

      {error && <div className="error" onClick={() => setError("")}>{error}</div>}

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th><input type="checkbox" checked={allShownSelected} onChange={toggleAll} /></th>
              <th>Contact</th>
              <th>Practice</th>
              <th>Email</th>
              <th>Status</th>
              <th>Next follow-up</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {shown.map((l) => (
              <tr key={l.id} onClick={() => setOpenId(l.id)} className={openId === l.id ? "open" : ""}>
                <td onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" checked={selected.has(l.id)} onChange={() => toggle(l.id)} />
                </td>
                <td>
                  <div className="strong">{fullName(l)}</div>
                  <div className="muted">{l.title}</div>
                </td>
                <td>
                  <div>{l.company}</div>
                  <div className="muted">{[l.city, l.state].filter(Boolean).join(", ")}</div>
                </td>
                <td className="muted">{l.email}</td>
                <td><span className={`badge s-${l.status}`}>{STATUS_LABELS[l.status] || l.status}</span></td>
                <td className={isDue(l) ? "due" : "muted"}>{l.next_follow_up_at || "—"}{isDue(l) && " · due"}</td>
                <td onClick={(e) => e.stopPropagation()} className="row-action">
                  {["new", "error"].includes(l.status) && (
                    <button className="small" onClick={() => act(() => api.run([l.id]))}>Research</button>
                  )}
                  {NEXT_SEND[l.status] && (
                    <button className="small" onClick={() => act(() => api.markSent(l.id))}>{NEXT_SEND[l.status]}</button>
                  )}
                </td>
              </tr>
            ))}
            {!shown.length && (
              <tr>
                <td colSpan={7} className="empty">
                  {leads.length ? "Nothing in this view." : "No leads yet. Click “Import leads” to add a CSV or paste text."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {showImport && (
        <ImportDialog
          onClose={() => setShowImport(false)}
          onDone={() => {
            setShowImport(false);
            refresh();
          }}
        />
      )}
      {openId && (
        <LeadDrawer id={openId} leads={leads} onClose={() => setOpenId(null)} onChange={refresh} />
      )}
    </div>
  );
}

function Stat({ label, value, alert, good }) {
  return (
    <div className={`stat ${alert ? "alert" : ""} ${good ? "good" : ""}`}>
      <div className="value">{value}</div>
      <div className="label">{label}</div>
    </div>
  );
}
