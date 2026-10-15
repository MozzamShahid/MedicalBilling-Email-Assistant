"""Copy the local SQLite CRM (backend/data/crm.db) into the DATABASE_URL database.

Run once from backend/:  .venv\\Scripts\\python -m app.migrate
Refuses to run if the target already has leads, so it can't create duplicates."""

from pathlib import Path

from dotenv import load_dotenv

from . import db


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    url = db.pg_url()
    if not url:
        raise SystemExit("Set DATABASE_URL in backend/.env first.")
    if not db.DB_PATH.exists():
        raise SystemExit(f"No local database at {db.DB_PATH}, nothing to copy.")

    db.init_db(url)
    with db.connect(url="") as local:
        leads = local.q("SELECT * FROM leads ORDER BY id")
        activity = local.q("SELECT lead_id, at, event FROM activity ORDER BY id")

    with db.connect(write=True, url=url) as pg:
        if pg.one("SELECT COUNT(*) AS n FROM leads")["n"]:
            raise SystemExit("The target database already has leads; not copying again.")
        cols = ["id", *db.LEAD_FIELDS, *db.SYSTEM_FIELDS]
        for lead in leads:
            pg.q(
                f"INSERT INTO leads ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [lead.get(c) for c in cols],
            )
        for a in activity:
            pg.q(
                "INSERT INTO activity (lead_id, at, event) VALUES (?, ?, ?)",
                (a["lead_id"], a["at"], a["event"]),
            )
        # New leads must get ids after the copied ones.
        pg.q("SELECT setval(pg_get_serial_sequence('leads', 'id'), (SELECT MAX(id) FROM leads))")
    print(f"Copied {len(leads)} leads and {len(activity)} activity entries.")


if __name__ == "__main__":
    main()
