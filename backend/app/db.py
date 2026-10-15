"""SQLite storage for the lead CRM."""

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "crm.db"

# Pipeline stages, in order. "researching" and "error" are system states.
STATUSES = [
    "new",
    "researching",
    "drafted",
    "sent",
    "follow_up_1",
    "follow_up_2",
    "replied",
    "meeting",
    "won",
    "not_interested",
    "bounced",
    "error",
]
# Statuses that still expect us to send another touch.
AWAITING_REPLY = ("sent", "follow_up_1")

LEAD_FIELDS = [
    "first_name",
    "last_name",
    "title",
    "company",
    "email",
    "phone",
    "website",
    "linkedin",
    "industry",
    "city",
    "state",
    "employees",
]
SYSTEM_FIELDS = [
    "status",
    "research",
    "subject",
    "body",
    "follow_up_1_subject",
    "follow_up_1_body",
    "follow_up_2_subject",
    "follow_up_2_body",
    "personalization_notes",
    "notes",
    "error",
    "last_contacted_at",
    "next_follow_up_at",
    "created_at",
    "updated_at",
]

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    cols = ",\n".join(f"{f} TEXT" for f in LEAD_FIELDS + SYSTEM_FIELDS)
    with _connect() as conn:
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS leads (id INTEGER PRIMARY KEY AUTOINCREMENT, {cols})"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                at TEXT NOT NULL,
                event TEXT NOT NULL
            )"""
        )


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(lead_id: int, event: str) -> None:
    with _lock, _connect() as conn:
        conn.execute(
            "INSERT INTO activity (lead_id, at, event) VALUES (?, ?, ?)",
            (lead_id, now(), event),
        )


def add_leads(leads: list[dict[str, str]]) -> tuple[list[int], int]:
    """Insert leads, skipping duplicates (same email, or same name + company).

    Returns (new ids, number of duplicates skipped)."""
    ids, skipped = [], 0
    with _lock, _connect() as conn:
        for lead in leads:
            email = (lead.get("email") or "").strip().lower()
            dup = None
            if email:
                dup = conn.execute(
                    "SELECT id FROM leads WHERE lower(email) = ?", (email,)
                ).fetchone()
            if not dup:
                dup = conn.execute(
                    "SELECT id FROM leads WHERE lower(first_name)=? AND lower(last_name)=? AND lower(company)=?",
                    tuple(
                        (lead.get(k) or "").strip().lower()
                        for k in ("first_name", "last_name", "company")
                    ),
                ).fetchone()
            if dup:
                skipped += 1
                continue
            row = {k: (lead.get(k) or "").strip() for k in LEAD_FIELDS}
            row.update(status="new", created_at=now(), updated_at=now())
            cur = conn.execute(
                f"INSERT INTO leads ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                list(row.values()),
            )
            ids.append(cur.lastrowid)
            conn.execute(
                "INSERT INTO activity (lead_id, at, event) VALUES (?, ?, ?)",
                (cur.lastrowid, now(), "Imported"),
            )
    return ids, skipped


def get_lead(lead_id: int) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
        if not row:
            return None
        lead = dict(row)
        lead["activity"] = [
            dict(a)
            for a in conn.execute(
                "SELECT at, event FROM activity WHERE lead_id = ? ORDER BY id DESC",
                (lead_id,),
            )
        ]
        return lead


def list_leads() -> list[dict[str, Any]]:
    with _connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM leads ORDER BY COALESCE(next_follow_up_at, '9999'), id DESC"
            )
        ]


def update_lead(lead_id: int, **fields: Any) -> None:
    allowed = set(LEAD_FIELDS + SYSTEM_FIELDS)
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = now()
    with _lock, _connect() as conn:
        conn.execute(
            f"UPDATE leads SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            [*fields.values(), lead_id],
        )


def delete_lead(lead_id: int) -> None:
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM leads WHERE id = ?", (lead_id,))
        conn.execute("DELETE FROM activity WHERE lead_id = ?", (lead_id,))


def mark_sent(lead_id: int, follow_up_days: list[int]) -> dict[str, Any]:
    """Advance a lead one touch: drafted -> sent -> follow_up_1 -> follow_up_2,
    and schedule the next follow-up date (none after the final touch)."""
    lead = get_lead(lead_id)
    if not lead:
        raise KeyError(lead_id)
    nxt = {"drafted": "sent", "new": "sent", "sent": "follow_up_1", "follow_up_1": "follow_up_2"}
    status = nxt.get(lead["status"])
    if not status:
        raise ValueError(f"Nothing left to send for a lead in status '{lead['status']}'")
    touch = ["sent", "follow_up_1", "follow_up_2"].index(status)
    next_at = None
    if touch < len(follow_up_days) and touch < 2:
        next_at = (datetime.now() + timedelta(days=follow_up_days[touch])).date().isoformat()
    update_lead(lead_id, status=status, last_contacted_at=now(), next_follow_up_at=next_at)
    label = ["Initial email", "Follow-up 1", "Follow-up 2"][touch]
    log(lead_id, f"{label} sent" + (f"; next follow-up {next_at}" if next_at else ""))
    return get_lead(lead_id)
