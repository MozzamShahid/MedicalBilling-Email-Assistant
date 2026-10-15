"""The research -> email crew for a single lead."""

import os
import re
from pathlib import Path
from typing import Any

import yaml
from crewai import LLM, Agent, Crew, Process, Task
from pydantic import BaseModel, Field

from .db import LEAD_FIELDS
from .tools import make_web_search_tool, scrape_site, scrape_website_tool

CONFIG = Path(__file__).resolve().parent.parent / "config"


class EmailSequence(BaseModel):
    subject: str = Field(description="Subject line of the first email")
    body: str = Field(description="Body of the first email, plain text, with greeting and sign-off")
    follow_up_1_subject: str
    follow_up_1_body: str
    follow_up_2_subject: str
    follow_up_2_body: str
    personalization_notes: str = Field(
        description="Which hook and pain were used, with sources, for human review"
    )


def _load(name: str) -> dict[str, Any]:
    return yaml.safe_load((CONFIG / name).read_text(encoding="utf-8"))


def _llm(env_var: str, default: str, temperature: float) -> LLM:
    return LLM(
        model=f"openrouter/{os.getenv(env_var, default)}",
        temperature=temperature,
    )


def pick_playbook(lead: dict[str, str]) -> str:
    """Pick the specialty playbook entry whose keywords match the lead."""
    playbook = _load("specialty_playbook.yaml")
    haystack = " ".join(
        lead.get(k) or "" for k in ("industry", "title", "company", "website")
    ).lower()
    for name, entry in playbook.items():
        if any(kw in haystack for kw in entry["keywords"]):
            break
    else:
        name, entry = "general", playbook["general"]
    points = "\n".join(f"- {p}" for p in entry["pain_points"])
    return f"Specialty guess: {name} (verify this against the website)\n{points}"


def sender_block() -> str:
    return yaml.safe_dump(_load("sender_profile.yaml"), sort_keys=False, allow_unicode=True)


def run_lead(lead: dict[str, str]) -> tuple[str, EmailSequence]:
    """Research one lead and write its email sequence.

    Returns (research brief markdown, email sequence)."""
    agents_cfg, tasks_cfg = _load("agents.yaml"), _load("tasks.yaml")

    researcher = Agent(
        config=agents_cfg["researcher"],
        llm=_llm("RESEARCH_MODEL", "deepseek/deepseek-v4-flash", 0.2),
        tools=[
            make_web_search_tool(int(os.getenv("WEB_SEARCH_BUDGET", "4"))),
            scrape_website_tool,
        ],
        max_iter=10,
        verbose=False,
    )
    writer = Agent(
        config=agents_cfg["writer"],
        llm=_llm("WRITER_MODEL", "deepseek/deepseek-v4-pro", 0.7),
        verbose=False,
    )
    research_task = Task(config=tasks_cfg["research_task"], agent=researcher)
    email_task = Task(
        config=tasks_cfg["email_task"],
        agent=writer,
        context=[research_task],
        output_pydantic=EmailSequence,
    )

    full_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    lead_block = "\n".join(
        f"- {k}: {v}" for k, v in lead.items() if v and k in LEAD_FIELDS
    )
    crew = Crew(
        agents=[researcher, writer],
        tasks=[research_task, email_task],
        process=Process.sequential,
        verbose=False,
    )
    result = crew.kickoff(
        inputs={
            "full_name": full_name or "the contact",
            "first_name": lead.get("first_name") or "there",
            "title": lead.get("title") or "unknown title",
            "company": lead.get("company") or "unknown company",
            "website": lead.get("website") or "no website given",
            "city": lead.get("city") or "",
            "lead_block": lead_block,
            "website_text": scrape_site(lead.get("website", "")) or "(no website given)",
            "playbook": pick_playbook(lead),
            "sender_block": sender_block(),
        }
    )
    emails = result.pydantic
    if not isinstance(emails, EmailSequence):
        raise RuntimeError(f"Writer did not return a valid email sequence: {result.raw[:500]}")
    return research_task.output.raw, _clean(emails)


def _clean(emails: EmailSequence) -> EmailSequence:
    """Remove em/en dashes, a common giveaway of AI-written copy that models
    keep using even when told not to."""
    data = {
        k: re.sub(r"\s*—\s*|\s+–\s+", ", ", v) if k != "personalization_notes" else v
        for k, v in emails.model_dump().items()
    }
    return EmailSequence(**data)

