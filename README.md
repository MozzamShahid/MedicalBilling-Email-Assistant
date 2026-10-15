# Medical Billing Outreach

Multi-agent cold outreach for a medical billing company, built on [CrewAI](https://github.com/crewAIInc/crewAI):

1. **Import leads**: an Apollo CSV export, or any pasted text (an AI step extracts the leads).
2. **Researcher agent** (DeepSeek V4 Flash via OpenRouter) scrapes the practice website, runs a few live web
   searches (reviews, new locations, job postings, the person), and writes a sourced brief with billing pain hypotheses.
3. **Writer agent** (DeepSeek V4 Pro) turns the brief into a 3-email sequence: an initial email plus 2 follow-ups.
4. **CRM** (React + SQLite) tracks each lead: new → ready to send → sent → follow-ups → replied / meeting / won,
   with follow-up due dates, notes, and an activity log.
5. **Export** the drafts to DOCX or PDF.

```
medbill-outreach/
├── backend/
│   ├── app/            FastAPI server, crew, tools, CRM database, import/export
│   ├── config/         ← the prompts live here (edit these to tune the emails)
│   │   ├── agents.yaml            agent roles and personas
│   │   ├── tasks.yaml             research and email instructions and rules
│   │   ├── sender_profile.yaml    YOUR company info and proof points (fill this in!)
│   │   └── specialty_playbook.yaml  billing pain points per specialty
│   └── .env            API key and model settings (never committed)
├── frontend/           React CRM (Vite)
└── leads/              drop your CSV files here (git-ignored)
```

## First-time setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
# Windows Application Control blocks fontTools' compiled extension; use the pure-Python build:
.\.venv\Scripts\pip install --force-reinstall --no-deps --no-binary fonttools fonttools
copy .env.example .env   # then paste your OpenRouter key into .env

cd ..\frontend
npm install
npm run build
```

## Run

```powershell
.\start.ps1
```

Open http://localhost:8000.

To work on the frontend with hot reload, keep the backend running and run `npm run dev` in `frontend/`
(http://localhost:5173 proxies `/api` to the backend).

## Before your first real campaign

- **Fill in `backend/config/sender_profile.yaml`.** Until you do, emails are signed "YOUR NAME / YOUR COMPANY NAME".
  Add real `proof_points` (results, client counts). The writer is told never to invent numbers, so this list is the
  only way stats end up in emails.
- Always read the **"Why this angle"** note and skim the research before sending. Both cite their sources.
  Leads marked `CHECK LEAD:` have data problems (wrong person, wrong website, practice closed).
- Skip leads that won't buy outsourced billing: residents, and employees of large health systems
  (Mount Sinai, Northwell, etc.) or PE-backed groups with in-house billing.

## Cost and speed

Roughly 2–4 minutes and a few cents per lead (the web searches are most of the cost, about $0.02 each).
Tune these in `backend/.env`:

| Setting | Default | What it does |
|---|---|---|
| `RESEARCH_MODEL` | `deepseek/deepseek-v4-flash` | researcher, web search, and text-import model |
| `WRITER_MODEL` | `deepseek/deepseek-v4-pro` | email writer model |
| `WEB_SEARCH_BUDGET` | `4` | max web searches per lead |
| `MAX_PARALLEL_LEADS` | `3` | leads researched at the same time |
| `FOLLOW_UP_DAYS` | `3,4` | days until follow-up 1, then follow-up 2 |

## Follow-up workflow

Send email 1 from your own mailbox ("Open in mail" or "Copy"), then click **Mark email 1 sent**. The lead
gets a follow-up date. Each day, open the **Follow-ups due** tab, send the next email in the same thread,
and click **Mark follow-up sent**. When someone answers, set the status to Replied / Meeting / Not interested.
That stops the reminders.
