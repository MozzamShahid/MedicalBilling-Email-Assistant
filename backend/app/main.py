"""HTTP API for the outreach CRM. Run: uvicorn app.main:app --reload"""

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, Response  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from . import auth, db  # noqa: E402
from .crew import BODY_LABELS, rewrite_body, run_lead, suggest_subjects  # noqa: E402
from .export import to_docx, to_pdf  # noqa: E402
from .importer import parse_csv, parse_text  # noqa: E402

log = logging.getLogger("outreach")
logging.basicConfig(level=logging.INFO)

FOLLOW_UP_DAYS = [int(d) for d in os.getenv("FOLLOW_UP_DAYS", "3,4").split(",")]
pool = ThreadPoolExecutor(max_workers=int(os.getenv("MAX_PARALLEL_LEADS", "3")))

app = FastAPI(title="Medical Billing Outreach")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)


@app.middleware("http")
async def check_login(request: Request, call_next):
    """Every /api route except login needs a valid session cookie."""
    path = request.url.path
    if path.startswith("/api/") and path not in ("/api/login", "/api/logout"):
        user = auth.current_user(request)
        if not user:
            return JSONResponse({"detail": "Please log in"}, status_code=401)
        request.state.user = user
    response = await call_next(request)
    if not path.startswith(("/api/", "/assets/")):
        # Always load the latest build of the page, never a stale cached copy.
        response.headers["Cache-Control"] = "no-store"
    return response


class Login(BaseModel):
    email: str
    password: str


@app.post("/api/login")
def login(body: Login, request: Request) -> Response:
    cookie, role = auth.login(body.email, body.password)
    resp = JSONResponse({"email": body.email.strip().lower(), "role": role})
    resp.set_cookie(
        auth.COOKIE,
        cookie,
        max_age=auth.MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",  # online (Railway) the cookie only travels over https
    )
    return resp


@app.post("/api/logout")
def logout() -> Response:
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE)
    return resp


@app.get("/api/me")
def me(request: Request) -> dict[str, str]:
    return request.state.user

db.init_db()
# A restart kills in-flight jobs; put those leads back so they can be re-run.
for _lead in db.list_leads():
    if _lead["status"] == "researching":
        db.update_lead(_lead["id"], status="drafted" if _lead["body"] else "new")


def _process(lead_id: int, prev_status: str) -> None:
    lead = db.get_lead(lead_id)
    if not lead:
        return
    try:
        research, emails = run_lead({k: lead.get(k) or "" for k in db.LEAD_FIELDS})
    except Exception as e:  # surface any failure in the CRM instead of losing it
        log.exception("Lead %s failed", lead_id)
        db.update_lead(
            lead_id, status="error" if prev_status in ("new", "error") else prev_status, error=str(e)[:2000]
        )
        db.log(lead_id, f"Research failed: {str(e)[:200]}")
        return
    # Rewriting a lead that is already mid-sequence keeps its place in the sequence.
    status = "drafted" if prev_status in ("new", "error", "drafted", "researching") else prev_status
    db.update_lead(lead_id, status=status, research=research, error="", **emails.model_dump())
    db.log(lead_id, "Emails rewritten" if prev_status != "new" else "Researched and emails drafted")


def _queue(ids: list[int]) -> list[int]:
    queued = []
    for lead_id in ids:
        lead = db.get_lead(lead_id)
        if lead and lead["status"] != "researching":
            db.update_lead(lead_id, status="researching", error="")
            pool.submit(_process, lead_id, lead["status"])
            queued.append(lead_id)
    return queued


@app.get("/api/leads")
def list_leads() -> list[dict[str, Any]]:
    return db.list_leads()


@app.get("/api/stats")
def stats() -> dict[str, Any]:
    leads = db.list_leads()
    today = date.today().isoformat()
    by_status = {s: 0 for s in db.STATUSES}
    for lead in leads:
        by_status[lead["status"]] = by_status.get(lead["status"], 0) + 1
    due = sum(
        1
        for lead in leads
        if lead["status"] in db.AWAITING_REPLY
        and lead["next_follow_up_at"]
        and lead["next_follow_up_at"] <= today
    )
    return {"total": len(leads), "by_status": by_status, "follow_ups_due": due}


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: int) -> dict[str, Any]:
    lead = db.get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "Lead not found")
    return lead


@app.post("/api/leads/import", dependencies=[Depends(auth.require_admin)])
async def import_leads(
    file: UploadFile | None = File(None),
    text: str = Form(""),
    auto_run: bool = Form(False),
) -> dict[str, Any]:
    if file is not None:
        leads = parse_csv((await file.read()).decode("utf-8", errors="replace"))
    elif text.strip():
        try:
            leads = parse_text(text)
        except Exception as e:
            raise HTTPException(400, f"Could not read leads from text: {e}") from e
    else:
        raise HTTPException(400, "Upload a CSV file or paste some text")
    ids, skipped = db.add_leads(leads)
    if auto_run:
        _queue(ids)
    return {"imported": len(ids), "skipped_duplicates": skipped, "ids": ids}


class RunRequest(BaseModel):
    ids: list[int] | None = None  # None = every lead still in "new" or "error"


@app.post("/api/leads/run")
def run_leads(req: RunRequest, request: Request) -> dict[str, Any]:
    ids = req.ids
    if request.state.user["role"] != "admin":
        # Senders may only rewrite emails that were already drafted, not research new leads.
        if ids is None or any(not (db.get_lead(i) or {}).get("body") for i in ids):
            raise HTTPException(403, "Only the admin can research new leads")
    if ids is None:
        ids = [lead["id"] for lead in db.list_leads() if lead["status"] in ("new", "error")]
    return {"queued": _queue(ids)}


class LeadUpdate(BaseModel):
    model_config = {"extra": "allow"}


@app.patch("/api/leads/{lead_id}")
def update_lead(lead_id: int, update: LeadUpdate) -> dict[str, Any]:
    fields = update.model_dump()
    lead = get_lead(lead_id)
    if "status" in fields and fields["status"] not in db.STATUSES:
        raise HTTPException(400, f"Unknown status {fields['status']}")
    if fields.get("status") and fields["status"] != lead["status"]:
        db.log(lead_id, f"Status: {lead['status']} -> {fields['status']}")
        if fields["status"] not in db.AWAITING_REPLY:
            fields.setdefault("next_follow_up_at", None)  # stop follow-up reminders
    db.update_lead(lead_id, **fields)
    return get_lead(lead_id)


@app.post("/api/leads/{lead_id}/sent")
def mark_sent(lead_id: int) -> dict[str, Any]:
    try:
        return db.mark_sent(lead_id, FOLLOW_UP_DAYS)
    except KeyError:
        raise HTTPException(404, "Lead not found") from None
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/leads/{lead_id}/subjects")
def subjects(lead_id: int) -> dict[str, list[str]]:
    lead = get_lead(lead_id)
    if not lead.get("body"):
        raise HTTPException(400, "Write the emails first")
    try:
        return {"subjects": suggest_subjects(lead)}
    except Exception as e:
        log.exception("Subject ideas failed for lead %s", lead_id)
        raise HTTPException(502, f"Could not get subject ideas: {e}") from e


class Rewrite(BaseModel):
    field: str  # body, follow_up_1_body, or follow_up_2_body


@app.post("/api/leads/{lead_id}/rewrite")
def rewrite(lead_id: int, req: Rewrite) -> dict[str, Any]:
    """Rewrite one email body, leaving the subject and the other emails alone."""
    lead = get_lead(lead_id)
    if req.field not in BODY_LABELS:
        raise HTTPException(400, f"Unknown email {req.field}")
    if not lead.get("body"):
        raise HTTPException(400, "Write the emails first")
    try:
        text = rewrite_body(lead, req.field)
    except Exception as e:
        log.exception("Rewrite failed for lead %s", lead_id)
        raise HTTPException(502, f"Could not rewrite the email: {e}") from e
    db.update_lead(lead_id, **{req.field: text})
    db.log(lead_id, f"{BODY_LABELS[req.field]} rewritten")
    return get_lead(lead_id)


@app.delete("/api/leads/{lead_id}", dependencies=[Depends(auth.require_admin)])
def delete_lead(lead_id: int) -> dict[str, bool]:
    db.delete_lead(lead_id)
    return {"ok": True}


@app.get("/api/export")
def export(fmt: str = "docx", ids: str = "", research: bool = False) -> Response:
    wanted = {int(i) for i in ids.split(",") if i.strip().isdigit()}
    leads = [
        lead
        for lead in db.list_leads()
        if lead.get("body") and (not wanted or lead["id"] in wanted)
    ]
    if not leads:
        raise HTTPException(400, "No drafted emails to export")
    if fmt == "pdf":
        data, media = to_pdf(leads, research), "application/pdf"
    else:
        fmt = "docx"
        data = to_docx(leads, research)
        media = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    name = f"cold-emails-{date.today().isoformat()}.{fmt}"
    return Response(data, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


# Serve the built React app (frontend/dist) from the same server when present.
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
