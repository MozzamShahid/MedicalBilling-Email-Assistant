"""The research -> email crew for a single lead."""

import json
import os
import re
from pathlib import Path
from typing import Any

import yaml
from crewai import LLM, Agent, Crew, Process, Task
from pydantic import BaseModel, Field

from .db import LEAD_FIELDS
from .llm import chat, litellm_model, provider
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
    extra = {}
    if provider() == "openrouter" and os.getenv("MODEL_REASONING", "off").lower() == "off":
        # DeepSeek V4 otherwise "thinks" in thousands of hidden, billed tokens
        # before writing a short email, which is slow and costs far more.
        extra["extra_body"] = {"reasoning": {"enabled": False}}
    return LLM(
        model=litellm_model(env_var, default),
        temperature=temperature,
        **({"additional_params": extra} if extra else {}),
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


def _lead_block(lead: dict[str, str]) -> str:
    # Apollo keyword lists run to thousands of characters; the first few are enough.
    return "\n".join(
        f"- {k}: {v[:500]}" for k, v in lead.items() if v and k in LEAD_FIELDS
    )


def run_lead(lead: dict[str, str]) -> tuple[str, EmailSequence]:
    """Research one lead and write its email sequence.

    RESEARCH_MODE=basic (default): no research agent and no web searches. The
    writer works from the Apollo data plus the scraped practice website, which
    costs one model call per lead. RESEARCH_MODE=deep adds the researcher agent
    with live web searches.

    Returns (research notes markdown, email sequence)."""
    agents_cfg, tasks_cfg = _load("agents.yaml"), _load("tasks.yaml")
    deep = os.getenv("RESEARCH_MODE", "basic").strip().lower() == "deep"
    lead_block = _lead_block(lead)
    website_text = (
        scrape_site(lead.get("website", ""))
        if deep
        else scrape_site(lead.get("website", ""), max_pages=3, max_chars=7000)
    ) or "(no website given)"

    writer = Agent(
        config=agents_cfg["writer"],
        llm=_llm("WRITER_MODEL", "deepseek/deepseek-v4-pro", 0.7),
        verbose=False,
    )
    email_task = Task(
        config=tasks_cfg["email_task"], agent=writer, output_pydantic=EmailSequence
    )
    agents, tasks = [writer], [email_task]
    if deep:
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
        research_task = Task(config=tasks_cfg["research_task"], agent=researcher)
        email_task.context = [research_task]
        agents, tasks = [researcher, writer], [research_task, email_task]
        research = "Use the research brief from the previous task, in your context above."
    else:
        research = (
            f"LEAD DATA (from Apollo; usually right, sometimes stale):\n{lead_block}\n\n"
            f"PRACTICE WEBSITE (scraped from {lead.get('website') or 'n/a'}):\n---\n"
            f"{website_text}\n---\n\n"
            f"SPECIALTY PLAYBOOK (common pains, hypotheses only):\n{pick_playbook(lead)}"
        )

    full_name = f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip()
    crew = Crew(agents=agents, tasks=tasks, process=Process.sequential, verbose=False)
    result = crew.kickoff(
        inputs={
            "full_name": full_name or "the contact",
            "first_name": lead.get("first_name") or "there",
            "title": lead.get("title") or "unknown title",
            "company": lead.get("company") or "unknown company",
            "website": lead.get("website") or "no website given",
            "city": lead.get("city") or "",
            "lead_block": lead_block,
            "website_text": website_text,
            "playbook": pick_playbook(lead),
            "sender_block": sender_block(),
            "research": research,
        }
    )
    emails = result.pydantic
    if not isinstance(emails, EmailSequence):
        raise RuntimeError(f"Writer did not return a valid email sequence: {result.raw[:500]}")
    notes = tasks[0].output.raw if deep else (
        "_Basic research: Apollo data + practice website, no web searches._\n\n"
        f"## Lead data\n{lead_block}\n\n## Website excerpt\n{website_text[:3000]}"
    )
    return notes, _clean(emails)


def suggest_subjects(lead: dict[str, Any]) -> list[str]:
    """Fresh subject line ideas for an already-drafted lead (one model call)."""
    prompt = _load("tasks.yaml")["subject_prompt"].format(
        lead=_lead_block({k: lead.get(k) or "" for k in LEAD_FIELDS if k != "keywords"}),
        email=lead.get("body", ""),
    )
    data = chat(
        {
            "model": os.getenv("WRITER_MODEL", "deepseek/deepseek-v4-pro"),
            "temperature": 0.9,
            # Without this, Flash can "think" for ~19k tokens (2+ minutes) on these prompts.
            "reasoning": {"enabled": False},
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
    )
    content = data["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:json)?|```$", "", content.strip()).strip()
    subjects = json.loads(content).get("subjects", [])
    return [s.strip().strip('"') for s in subjects if isinstance(s, str) and s.strip()][:6]


BODY_LABELS = {
    "body": "Email 1",
    "follow_up_1_body": "Follow-up 1",
    "follow_up_2_body": "Follow-up 2",
}


def rewrite_body(lead: dict[str, Any], field: str) -> str:
    """Rewrite one email body of an already-drafted lead (one model call)."""
    tasks = _load("tasks.yaml")
    full_name = f"{lead.get('first_name') or ''} {lead.get('last_name') or ''}".strip()
    values = {
        "full_name": full_name or "the contact",
        "first_name": lead.get("first_name") or "there",
        "title": lead.get("title") or "unknown title",
        "company": lead.get("company") or "unknown company",
        "research": lead.get("research") or _lead_block(lead),
        "sender_block": sender_block(),
    }
    rules = tasks["email_task"]["description"]
    for k, v in values.items():  # plain replace: the rules contain other braces
        rules = rules.replace("{" + k + "}", v)
    sequence = "\n\n".join(
        f"--- {label} ---\n{lead.get(k) or ''}" for k, label in BODY_LABELS.items()
    )
    prompt = rules + "\n\n" + tasks["rewrite_prompt"].format(
        which=BODY_LABELS[field], sequence=f"Subject: {lead.get('subject')}\n\n{sequence}"
    )
    data = chat(
        {
            "model": os.getenv("WRITER_MODEL", "deepseek/deepseek-v4-pro"),
            "temperature": 0.9,
            # Without this, Flash can "think" for ~19k tokens (2+ minutes) on these prompts.
            "reasoning": {"enabled": False},
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": prompt}],
        }
    )
    content = data["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:json)?|```$", "", content.strip()).strip()
    text = json.loads(content)["text"].strip()
    return _clean(EmailSequence(**{**_empty_sequence(), "body": text})).body


def _empty_sequence() -> dict[str, str]:
    return {k: "" for k in EmailSequence.model_fields}


def _clean(emails: EmailSequence) -> EmailSequence:
    """Remove em/en dashes and "reach out", common giveaways of AI-written copy
    that models keep using even when told not to."""

    def fix(text: str) -> str:
        text = re.sub(r"\s*—\s*|\s+–\s+", ", ", text)
        return re.sub(r"\breach(ing)? out to\b", "talk to", text)

    data = {
        k: fix(v) if k != "personalization_notes" else v
        for k, v in emails.model_dump().items()
    }
    return EmailSequence(**data)

