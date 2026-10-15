import { useState } from "react";
import { api } from "./api.js";

export default function ImportDialog({ onClose, onDone }) {
  const [mode, setMode] = useState("csv");
  const [file, setFile] = useState(null);
  const [text, setText] = useState("");
  const [autoRun, setAutoRun] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");

  const submit = async () => {
    const form = new FormData();
    if (mode === "csv") form.append("file", file);
    else form.append("text", text);
    form.append("auto_run", autoRun);
    setBusy(true);
    setError("");
    try {
      setResult(await api.importLeads(form));
    } catch (e) {
      setError(e.message);
    }
    setBusy(false);
  };

  return (
    <div className="modal-bg" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h2>Import leads</h2>
        {result ? (
          <>
            <p>
              Imported <b>{result.imported}</b> lead(s)
              {result.skipped_duplicates > 0 && `, skipped ${result.skipped_duplicates} duplicate(s)`}.
              {autoRun && result.imported > 0 && " Research has started; rows update as each lead finishes."}
            </p>
            <div className="modal-actions">
              <button className="primary" onClick={onDone}>Done</button>
            </div>
          </>
        ) : (
          <>
            <div className="seg">
              <button className={mode === "csv" ? "active" : ""} onClick={() => setMode("csv")}>CSV file</button>
              <button className={mode === "text" ? "active" : ""} onClick={() => setMode("text")}>Paste text</button>
            </div>
            {mode === "csv" ? (
              <div className="field">
                <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files[0])} />
                <p className="muted">
                  Apollo exports work as-is. Recognised columns include First Name, Last Name, Title, Company,
                  Email, Website, Industry, City, State, Person Linkedin Url, phone columns.
                </p>
              </div>
            ) : (
              <div className="field">
                <textarea
                  rows={10}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  placeholder={"Paste anything: Apollo profile text, a list, email signatures…\n\nDr. Sarah Kim, owner, Bright Skin Dermatology, sarah@brightskinderm.com, brightskinderm.com, Plano TX"}
                />
                <p className="muted">An AI step extracts the leads from the text. It doesn't invent missing details.</p>
              </div>
            )}
            <label className="check">
              <input type="checkbox" checked={autoRun} onChange={(e) => setAutoRun(e.target.checked)} />
              Start research and email drafting right away
            </label>
            {error && <div className="error">{error}</div>}
            <div className="modal-actions">
              <button onClick={onClose}>Cancel</button>
              <button
                className="primary"
                disabled={busy || (mode === "csv" ? !file : !text.trim())}
                onClick={submit}
              >
                {busy ? "Importing…" : "Import"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
