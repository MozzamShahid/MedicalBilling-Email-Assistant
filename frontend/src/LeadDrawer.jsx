import { marked } from "marked";
import { useEffect, useState } from "react";
import { api } from "./api.js";
import { NEXT_SEND, STATUS_LABELS, emailsSent, fullName, gmailUrl, nextStep } from "./App.jsx";

const EMAILS = [
  ["Email 1", "subject", "body"],
  ["Follow-up 1", "follow_up_1_subject", "follow_up_1_body"],
  ["Follow-up 2", "follow_up_2_subject", "follow_up_2_body"],
];

export default function LeadDrawer({ id, leads, isAdmin, onClose, onChange }) {
  const [ideas, setIdeas] = useState(null); // null | "loading" | string[]
  const [rewriting, setRewriting] = useState(null); // index of the email being rewritten
  useEffect(() => setIdeas(null), [id]);
  const [lead, setLead] = useState(null);
  const [draft, setDraft] = useState({});
  const [tab, setTab] = useState("emails");
  const [msg, setMsg] = useState("");
  const [opened, setOpened] = useState(null); // email index just opened in Gmail

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
  const getIdeas = () => {
    setIdeas("loading");
    api.subjects(id).then((r) => setIdeas(r.subjects)).catch((e) => { setIdeas(null); flash(e.message); });
  };
  const rewriteOne = (i, field) => {
    setRewriting(i);
    run(async () => {
      try {
        await api.rewrite(id, field);
        const { [field]: _, ...rest } = draft; // drop unsaved edits to that email
        setDraft(rest);
      } finally {
        setRewriting(null);
      }
    }, "Email rewritten");
  };
  // Picking an idea saves it right away, so Gmail opens with the new subject.
  const pickSubject = (subject) => {
    const { subject: _, ...rest } = draft;
    setDraft(rest);
    run(() => api.update(id, { subject }), "Subject updated");
  };
  const copy = (text) => navigator.clipboard.writeText(text).then(() => flash("Copied"));
  // Date each email was logged as sent, from the activity log.
  const sentDate = (i) => {
    const prefix = ["Initial email sent", "Follow-up 1 sent", "Follow-up 2 sent"][i];
    const a = [...lead.activity].reverse().find((e) => e.event.startsWith(prefix));
    return a && new Date(a.at).toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };

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
          {lead.body ? (
            <button
              disabled={lead.status === "researching"}
              title="Write a fresh set of emails for this lead"
              onClick={() =>
                confirm("Rewrite all 3 emails? Your edits to the current drafts will be replaced.") &&
                run(() => api.run([id]), "Rewriting…")
              }
            >
              ↻ Rewrite emails
            </button>
          ) : (
            isAdmin && (
              <button disabled={lead.status === "researching"} onClick={() => run(() => api.run([id]), "Research started")}>
                Research
              </button>
            )
          )}
          {isAdmin && (
            <button
              className="danger"
              onClick={() => confirm(`Delete ${fullName(lead)}?`) && api.remove(id).then(() => { onChange(); onClose(); })}
            >
              Delete
            </button>
          )}
          {msg && <span className="flash">{msg}</span>}
        </div>
        {lead.next_follow_up_at && <div className="muted">Next follow-up: <b>{lead.next_follow_up_at}</b></div>}
        {lead.error && lead.status !== "researching" && <div className="error">{lead.error}</div>}
        {lead.status === "researching" && <div className="info">Writing the emails… this usually takes under a minute.</div>}

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
                <div className={`notes-box ${/^(CHECK LEAD|POOR FIT)/.test(lead.personalization_notes) ? "warn" : ""}`}>
                  <b>Why this angle:</b> {lead.personalization_notes}
                </div>
              )}
              {EMAILS.map(([label, sk, bk], i) => {
                const sent = i < emailsSent(lead);
                const isNext = i === nextStep(lead);
                const subject = i === 0 ? val("subject") : `Re: ${val("subject")}`;
                return (
                  <div className={`email-card ${sent ? "sent" : isNext ? "next" : ""}`} key={label}>
                    <div className="email-head">
                      <b>{label}</b>
                      <span className={`send-state ${sent ? "done" : isNext ? "next" : "muted"}`}>
                        {sent ? `✓ Sent ${sentDate(i) || ""}` : isNext ? "Next to send" : "Not sent yet"}
                      </span>
                      <span className="spacer" />
                      <button
                        className="small"
                        title="Write a fresh version of just this email"
                        disabled={rewriting !== null || lead.status === "researching"}
                        onClick={() => rewriteOne(i, bk)}
                      >
                        {rewriting === i ? "Rewriting…" : "↻ Rewrite"}
                      </button>
                      <button className="small" onClick={() => copy(`${subject}\n\n${val(bk)}`)}>Copy</button>
                      {lead.email && (
                        <a
                          className={`btn small ${isNext ? "primary" : ""}`}
                          href={gmailUrl(lead, subject, val(bk))}
                          target="_blank"
                          rel="noreferrer"
                          onClick={() => isNext && setOpened(i)}
                        >
                          Open in Gmail
                        </a>
                      )}
                    </div>
                    {isNext && opened === i && (
                      <div className="confirm-sent">
                        Did you send it in Gmail?
                        <button className="small primary" onClick={() => { setOpened(null); run(() => api.markSent(id), `${label} marked sent`); }}>
                          Yes, I sent it
                        </button>
                        <button className="small" onClick={() => setOpened(null)}>Not yet</button>
                      </div>
                    )}
                    {i === 0 ? (
                      <>
                        <div className="subject-row">
                          <input value={val(sk)} onChange={(e) => setDraft({ ...draft, [sk]: e.target.value })} />
                          <button
                            className="small"
                            title="Get fresh subject line ideas"
                            disabled={ideas === "loading"}
                            onClick={getIdeas}
                          >
                            {ideas === "loading" ? "Thinking…" : "↻ Subject ideas"}
                          </button>
                        </div>
                        {Array.isArray(ideas) && (
                          <div className="ideas">
                            <span className="muted">Click one to use it:</span>
                            {ideas.map((s) => (
                              <button key={s} className="idea" onClick={() => pickSubject(s)}>{s}</button>
                            ))}
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="thread-subject">Subject: {subject} (sends as a reply in the same thread)</div>
                    )}
                    <textarea rows={i === 0 ? 9 : 6} value={val(bk)} onChange={(e) => setDraft({ ...draft, [bk]: e.target.value })} />
                    <div className="muted small-text">{val(bk).split(/\s+/).filter(Boolean).length} words</div>
                  </div>
                );
              })}
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
