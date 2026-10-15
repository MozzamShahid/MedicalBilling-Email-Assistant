import { marked } from "marked";
import { useEffect, useState } from "react";
import { api } from "./api.js";
import { NEXT_SEND, STATUS_LABELS, fullName } from "./App.jsx";

const EMAILS = [
  ["Email 1", "subject", "body"],
  ["Follow-up 1", "follow_up_1_subject", "follow_up_1_body"],
  ["Follow-up 2", "follow_up_2_subject", "follow_up_2_body"],
];

export default function LeadDrawer({ id, leads, onClose, onChange }) {
  const [lead, setLead] = useState(null);
  const [draft, setDraft] = useState({});
  const [tab, setTab] = useState("emails");
  const [msg, setMsg] = useState("");

  // Re-fetch when the row in the table changes (status updates while researching).
  const row = leads.find((l) => l.id === id);
  useEffect(() => {
    api.lead(id).then((l) => {
      setLead(l);
      setDraft({});
    });
  }, [id, row?.updated_at]);

  if (!lead) return null;
  const val = (k) => (k in draft ? draft[k] : lead[k] || "");
  const dirty = Object.keys(draft).length > 0;

  const flash = (m) => {
    setMsg(m);
    setTimeout(() => setMsg(""), 2000);
  };
  const run = async (fn, done) => {
    try {
      await fn();
      if (done) flash(done);
    } catch (e) {
      flash(e.message);
    }
    onChange();
    setLead(await api.lead(id));
  };
  const save = () => run(() => api.update(id, draft).then(() => setDraft({})), "Saved");
  const copy = (text) => navigator.clipboard.writeText(text).then(() => flash("Copied"));
  const mailto = (subject, body) =>
    `mailto:${lead.email}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;

  return (
    <div className="drawer-bg" onClick={onClose}>
      <aside className="drawer" onClick={(e) => e.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <h2>{fullName(lead)}</h2>
            <div className="muted">{lead.title}</div>
            <div>
              {lead.company}
              {lead.website && (
                <>
                  {" · "}
                  <a href={lead.website.startsWith("http") ? lead.website : `https://${lead.website}`} target="_blank" rel="noreferrer">
                    website
                  </a>
                </>
              )}
              {lead.linkedin && (
                <>
                  {" · "}
                  <a href={lead.linkedin} target="_blank" rel="noreferrer">LinkedIn</a>
                </>
              )}
            </div>
            <div className="muted">
              {[lead.email, lead.phone, [lead.city, lead.state].filter(Boolean).join(", ")].filter(Boolean).join(" · ")}
            </div>
          </div>
          <button className="close" onClick={onClose}>×</button>
        </div>

        <div className="drawer-controls">
          <select value={lead.status} onChange={(e) => run(() => api.update(id, { status: e.target.value }), "Status updated")}>
            {Object.entries(STATUS_LABELS).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
          {NEXT_SEND[lead.status] && (
            <button className="primary" onClick={() => run(() => api.markSent(id), "Logged")}>{NEXT_SEND[lead.status]}</button>
          )}
          <button
            disabled={lead.status === "researching"}
            onClick={() => run(() => api.run([id]), "Research started")}
          >
            {lead.body ? "Regenerate" : "Research"}
          </button>
          <button
            className="danger"
            onClick={() => confirm(`Delete ${fullName(lead)}?`) && api.remove(id).then(() => { onChange(); onClose(); })}
          >
            Delete
          </button>
          {msg && <span className="flash">{msg}</span>}
        </div>
        {lead.next_follow_up_at && <div className="muted">Next follow-up: <b>{lead.next_follow_up_at}</b></div>}
        {lead.status === "error" && <div className="error">{lead.error}</div>}
        {lead.status === "researching" && <div className="info">Researching and writing… this usually takes 2–4 minutes.</div>}

        <div className="tabs">
          {["emails", "research", "notes", "activity"].map((t) => (
            <button key={t} className={`tab ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
              {t[0].toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>

        {tab === "emails" && (
          lead.body ? (
            <>
              {lead.personalization_notes && (
                <div className={`notes-box ${lead.personalization_notes.startsWith("CHECK LEAD") ? "warn" : ""}`}>
                  <b>Why this angle:</b> {lead.personalization_notes}
                </div>
              )}
              {EMAILS.map(([label, sk, bk]) => (
                <div className="email-card" key={label}>
                  <div className="email-head">
                    <b>{label}</b>
                    <span className="spacer" />
                    <button className="small" onClick={() => copy(`${val(sk)}\n\n${val(bk)}`)}>Copy</button>
                    {lead.email && <a className="btn small" href={mailto(val(sk), val(bk))}>Open in mail</a>}
                  </div>
                  <input value={val(sk)} onChange={(e) => setDraft({ ...draft, [sk]: e.target.value })} />
                  <textarea rows={9} value={val(bk)} onChange={(e) => setDraft({ ...draft, [bk]: e.target.value })} />
                  <div className="muted small-text">{val(bk).split(/\s+/).filter(Boolean).length} words</div>
                </div>
              ))}
              {dirty && <button className="primary" onClick={save}>Save edits</button>}
            </>
          ) : (
            <p className="muted">No emails yet. Click “Research” to have the agents research this lead and write the sequence.</p>
          )
        )}

        {tab === "research" && (
          lead.research ? (
            <div className="markdown" dangerouslySetInnerHTML={{ __html: marked.parse(lead.research) }} />
          ) : (
            <p className="muted">No research yet.</p>
          )
        )}

        {tab === "notes" && (
          <>
            <textarea rows={10} value={val("notes")} placeholder="Call notes, replies, objections…" onChange={(e) => setDraft({ ...draft, notes: e.target.value })} />
            {dirty && <button className="primary" onClick={save}>Save notes</button>}
          </>
        )}

        {tab === "activity" && (
          <ul className="activity">
            {lead.activity.map((a, i) => (
              <li key={i}><span className="muted">{a.at.replace("T", " ")}</span> {a.event}</li>
            ))}
          </ul>
        )}
      </aside>
    </div>
  );
}
