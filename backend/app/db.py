"""Storage for the lead CRM: Postgres (e.g. Supabase) when DATABASE_URL is set,
otherwise a local SQLite file. Queries are written once with ? placeholders."""

import os
import sqlite3
import threading
from contextlib import contextmanager, nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

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
    "seniority",
    "keywords",
    "technologies",
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

_sqlite_lock = threading.Lock()


def pg_url() -> str:
    return os.getenv("DATABASE_URL", "").strip()


class Conn:
    """One connection with a tiny query API that hides SQLite/Postgres differences."""

    def __init__(self, raw: Any, pg: bool):
        self.raw, self.pg = raw, pg

    def q(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        if self.pg:
            sql = sql.replace("%", "%%").replace("?", "%s")
        cur = self.raw.execute(sql, params)
        if cur.description is None:
            return []
        return [dict(r) for r in cur.fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        rows = self.q(sql, params)
        return rows[0] if rows else None


_pools: dict[str, Any] = {}


def _pool(url: str) -> Any:
    """A small pool per database URL. Opening a connection to Supabase takes
    over a second, so connections are reused; idle ones close after 2 minutes."""
    if url not in _pools:
        from psycopg.rows import dict_row
        from psycopg_pool import ConnectionPool

        _pools[url] = ConnectionPool(
            url,
            min_size=0,
            max_size=5,
            max_idle=120,
            # prepare_threshold=None: Supabase's transaction pooler can't use prepared statements.
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
            open=True,
        )
    return _pools[url]


@contextmanager
def connect(write: bool = False, url: str | None = None) -> Iterator[Conn]:
    """Get a connection, commit on success, roll back on error.

    `url=""` forces the local SQLite file (used by the Supabase migration)."""
    url = pg_url() if url is None else url
    if url:
        # The pool commits (or rolls back on error) and takes the connection back.
        with _pool(url).connection() as raw:
            yield Conn(raw, True)
        return
    else:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        raw = sqlite3.connect(DB_PATH, check_same_thread=False)
        raw.row_factory = sqlite3.Row
    # SQLite allows one writer at a time.
    with _sqlite_lock if write else nullcontext():
        try:
            yield Conn(raw, bool(url))
            raw.commit()
        finally:
            raw.close()


def init_db(url: str | None = None) -> None:
    cols = ",\n".join(f"{f} TEXT" for f in LEAD_FIELDS + SYSTEM_FIELDS)
    with connect(write=True, url=url) as db:
        id_col = "BIGSERIAL PRIMARY KEY" if db.pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
        db.q(f"CREATE TABLE IF NOT EXISTS leads (id {id_col}, {cols})")
        db.q(
            f"""CREATE TABLE IF NOT EXISTS activity (
                id {id_col},
                lead_id INTEGER NOT NULL,
                at TEXT NOT NULL,
                event TEXT NOT NULL
            )"""
        )
        db.q("CREATE INDEX IF NOT EXISTS activity_lead_id ON activity (lead_id)")
        # Add columns introduced after the database was first created.
        if db.pg:
            existing = {
                r["column_name"]
                for r in db.q(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = current_schema() AND table_name = 'leads'"
                )
            }
            # Supabase exposes the public schema over its web API; with row level
            # security on and no policies, only this app's direct connection can read it.
            db.q("ALTER TABLE leads ENABLE ROW LEVEL SECURITY")
            db.q("ALTER TABLE activity ENABLE ROW LEVEL SECURITY")
        else:
            existing = {r["name"] for r in db.q("PRAGMA table_info(leads)")}
        for f in LEAD_FIELDS + SYSTEM_FIELDS:
            if f not in existing:
                db.q(f"ALTER TABLE leads ADD COLUMN {f} TEXT")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def log(lead_id: int, event: str) -> None:
    with connect(write=True) as db:
        db.q("INSERT INTO activity (lead_id, at, event) VALUES (?, ?, ?)", (lead_id, now(), event))


def add_leads(leads: list[dict[str, str]]) -> tuple[list[int], list[dict[str, Any]]]:
    """Insert leads, skipping duplicates (same email, or same name + company).

    Returns (new ids, the skipped leads with who they matched and why)."""
    ids, skipped = [], []
    with connect(write=True) as db:
        for lead in leads:
            email = (lead.get("email") or "").strip().lower()
            dup = None
            if email:
                dup = db.one("SELECT id, status FROM leads WHERE lower(email) = ?", (email,))
            if not dup:
                dup = db.one(
                    "SELECT id, status FROM leads WHERE lower(first_name)=? AND lower(last_name)=? AND lower(company)=?",
                    tuple(
                        (lead.get(k) or "").strip().lower()
                        for k in ("first_name", "last_name", "company")
                    ),
                )
            if dup:
                skipped.append(
                    {
                        "name": f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip(),
                        "company": lead.get("company") or "",
                        "email": lead.get("email") or "",
                        "existing_id": dup["id"],
                        "existing_status": dup["status"],
                        "reason": "listed twice in this file" if dup["id"] in ids else "already in your list",
                    }
                )
                continue
            row = {k: (lead.get(k) or "").strip() for k in LEAD_FIELDS}
            row.update(status="new", created_at=now(), updated_at=now())
            new_id = db.one(
                f"INSERT INTO leads ({', '.join(row)}) VALUES ({', '.join('?' * len(row))}) RETURNING id",
                list(row.values()),
            )["id"]
            ids.append(new_id)
            db.q(
                "INSERT INTO activity (lead_id, at, event) VALUES (?, ?, ?)",
                (new_id, now(), "Imported"),
            )
    return ids, skipped


# How many of the 3 emails were logged as sent (kept after the lead replies).
EMAILS_SENT_SQL = """(SELECT COUNT(*) FROM activity a WHERE a.lead_id = leads.id
    AND (a.event LIKE 'Initial email sent%' OR a.event LIKE 'Follow-up _ sent%'))"""


def get_lead(lead_id: int) -> dict[str, Any] | None:
    with connect() as db:
        lead = db.one(
            f"SELECT *, {EMAILS_SENT_SQL} AS emails_sent FROM leads WHERE id = ?", (lead_id,)
        )
        if not lead:
            return None
        lead["activity"] = db.q(
            "SELECT at, event FROM activity WHERE lead_id = ? ORDER BY id DESC", (lead_id,)
        )
        return lead


# Large text the lead table never shows; get_lead still returns it for the drawer.
_LIST_SKIP = {"research", "keywords", "technologies"}


def list_leads() -> list[dict[str, Any]]:
    cols = ", ".join(["id", *(f for f in LEAD_FIELDS + SYSTEM_FIELDS if f not in _LIST_SKIP)])
    with connect() as db:
        return db.q(
            f"SELECT {cols}, {EMAILS_SENT_SQL} AS emails_sent FROM leads "
            "ORDER BY COALESCE(next_follow_up_at, '9999'), id DESC"
        )


def update_lead(lead_id: int, **fields: Any) -> None:
    allowed = set(LEAD_FIELDS + SYSTEM_FIELDS)
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = now()
    with connect(write=True) as db:
        db.q(
            f"UPDATE leads SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
            [*fields.values(), lead_id],
        )


def delete_lead(lead_id: int) -> None:
    with connect(write=True) as db:
        db.q("DELETE FROM leads WHERE id = ?", (lead_id,))
        db.q("DELETE FROM activity WHERE lead_id = ?", (lead_id,))


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
