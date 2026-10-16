import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

// The three touches, and which lead fields hold each one's text.
export const STEPS = [
  { label: "Email 1", short: "Email 1", body: "body" },
  { label: "Follow-up 1", short: "FU 1", body: "follow_up_1_body" },
  { label: "Follow-up 2", short: "FU 2", body: "follow_up_2_body" },
];
const SENT_FROM_STATUS = { sent: 1, follow_up_1: 2, follow_up_2: 3 };
export const emailsSent = (l) => Math.max(l.emails_sent || 0, SENT_FROM_STATUS[l.status] || 0);
// Index of the email to send next, or null when nothing is waiting to go out.
export const nextStep = (l) => (NEXT_SEND[l.status] && l.body ? emailsSent(l) : null);

// Follow-ups go out as replies so they read as one thread.
export const stepSubject = (l, i) => (i === 0 ? l.subject : `Re: ${l.subject}`);
export const gmailUrl = (l, subject, body) =>
  "https://mail.google.com/mail/?view=cm&fs=1" +
  `&to=${encodeURIComponent(l.email || "")}` +
  `&su=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

// Checks the login, then shows the CRM. Admin sees everything; the sender
// (who only sends the drafted emails) gets no import, research, or delete.
export default function App() {
  const [user, setUser] = useState(undefined); // undefined = still checking
  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
    const onLoggedOut = () => setUser(null);
    window.addEventListener("logged-out", onLoggedOut);
    return () => window.removeEventListener("logged-out", onLoggedOut);
  }, []);
  if (user === undefined) return null;
  if (!user) return <Login onLogin={setUser} />;
  return <Crm user={user} onLogout={() => api.logout().then(() => setUser(null))} />;
}

function Login({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = (e) => {
    e.preventDefault();
    api.login(email, password).then(onLogin).catch((err) => setError(err.message));
  };
  return (
    <form className="login" onSubmit={submit}>
      <h1>Outreach CRM</h1>
      <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} autoFocus />
      <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <button className="primary" type="submit">Log in</button>
      {error && <div className="error">{error}</div>}
    </form>
  );
}

function Crm({ user, onLogout }) {
  const isAdmin = user.role === "admin";
  const [leads, setLeads] = useState([]);
  const [view, setView] = useState("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(new Set());
  const [openId, setOpenId] = useState(null);
  const [showImport, setShowImport] = useState(false);
  const [withResearch, setWithResearch] = useState(false);
  const [error, setError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [working, setWorking] = useState(false); // a toolbar/bulk action is in flight

  // The list can take a few seconds from the cloud database; never stack requests.
  const inFlight = useRef(null);
  const refresh = useCallback(() => {
    if (!inFlight.current) {
      inFlight.current = api
        .leads()
        .then((l) => {
          setLeads(l);
          setLoaded(true);
        })
        .catch((e) => setError(e.message))
        .finally(() => (inFlight.current = null));
    }
    return inFlight.current;
  }, []);

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
    if (working) return; // ignore double clicks while the last action runs
    setError("");
    setWorking(true);
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setWorking(false);
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
  const selectedLeads = leads.filter((l) => selected.has(l.id));

  // Bulk actions run one lead at a time through the normal endpoints.
  const bulk = (fn, confirmText) => {
    if (confirmText && !confirm(confirmText)) return;
    act(async () => {
      for (const l of selectedLeads) await fn(l);
      setSelected(new Set());
    });
  };
  // Mark one specific step sent; only leads waiting on exactly that step move.
  const atStep = (i) => selectedLeads.filter((l) => nextStep(l) === i);
  const bulkMarkStep = (i) => {
    const ready = atStep(i);
    const skipped = selectedLeads.length - ready.length;
    const text =
      `Mark ${STEPS[i].label} as sent for ${ready.length} lead(s)? Each gets its next follow-up date.` +
      (skipped ? `\n\n${skipped} selected lead(s) are at a different step and will be skipped.` : "");
    bulk((l) => (nextStep(l) === i ? api.markSent(l.id) : null), text);
  };

  return (
    <div className="app">
      <header>
        <div className="title-row">
          <h1>Outreach CRM</h1>
          <span className="muted">{user.email} · {isAdmin ? "admin" : "sender"}</span>
          <button className="small" onClick={onLogout}>Log out</button>
        </div>
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
        {isAdmin && <button className="primary" onClick={() => setShowImport(true)}>+ Import leads</button>}
        {isAdmin && <button
          disabled={working}
          onClick={() => act(() => api.run(selectedIds.length ? selectedIds : null))}
          title="Research leads and draft emails. With nothing selected, runs every New / Error lead."
        >
          {selectedIds.length ? `Research ${selectedIds.length} selected` : "Research all new"}
        </button>}
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

      {selectedIds.length > 0 && (
        <div className="bulk-bar">
          <b>{selectedIds.length} selected</b>
          {STEPS.map((s, i) => (
            <button key={i} className="primary" disabled={!atStep(i).length} onClick={() => bulkMarkStep(i)}>
              Mark {s.label} sent ({atStep(i).length})
            </button>
          ))}
          <select
            value=""
            onChange={(e) => {
              const status = e.target.value;
              if (status) bulk((l) => api.update(l.id, { status }), `Set ${selectedIds.length} lead(s) to "${STATUS_LABELS[status]}"?`);
            }}
          >
            <option value="">Set status…</option>
            {Object.entries(STATUS_LABELS)
              .filter(([k]) => !["researching", "error"].includes(k))
              .map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
          </select>
          {isAdmin && (
            <button className="danger" onClick={() => bulk((l) => api.remove(l.id), `Delete ${selectedIds.length} lead(s)? This can't be undone.`)}>
              Delete
            </button>
          )}
          <button onClick={() => setSelected(new Set())}>Clear selection</button>
        </div>
      )}

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
              <th>Sent</th>
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
                <td>
                  <div className="steps">
                    {STEPS.map((s, i) => (
                      <span key={i} className={`step ${i < emailsSent(l) ? "done" : i === nextStep(l) ? "next" : ""}`}>
                        {i < emailsSent(l) ? "✓ " : ""}{s.short}
                      </span>
                    ))}
                  </div>
                </td>
                <td className={isDue(l) ? "due" : "muted"}>{l.next_follow_up_at || "—"}{isDue(l) && " · due"}</td>
                <td onClick={(e) => e.stopPropagation()} className="row-action">
                  {isAdmin && ["new", "error"].includes(l.status) && (
                    <button className="small" onClick={() => act(() => api.run([l.id]))}>Research</button>
                  )}
                  {nextStep(l) !== null && l.email && (
                    <a
                      className="btn small primary"
                      href={gmailUrl(l, stepSubject(l, nextStep(l)), l[STEPS[nextStep(l)].body])}
                      target="_blank"
                      rel="noreferrer"
                    >
                      Gmail: {STEPS[nextStep(l)].short}
                    </a>
                  )}
                  {NEXT_SEND[l.status] && (
                    <button className="small" onClick={() => act(() => api.markSent(l.id))}>{NEXT_SEND[l.status]}</button>
                  )}
                </td>
              </tr>
            ))}
            {!shown.length && (
              <tr>
                <td colSpan={8} className="empty">
                  {!loaded ? "Loading leads…" : leads.length ? "Nothing in this view." : "No leads yet. Click “Import leads” to add a CSV or paste text."}
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
        <LeadDrawer isAdmin={isAdmin} id={openId} leads={leads} onClose={() => setOpenId(null)} onChange={refresh} />
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
