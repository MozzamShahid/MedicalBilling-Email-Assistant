"""Turn an Apollo CSV export or free-form pasted text into lead dicts."""

import csv
import io
import json
import os
import re

import requests

from .db import LEAD_FIELDS

# Lowercased CSV header -> our field. Covers Apollo exports plus common variants.
HEADER_ALIASES = {
    "first name": "first_name",
    "first_name": "first_name",
    "firstname": "first_name",
    "last name": "last_name",
    "last_name": "last_name",
    "lastname": "last_name",
    "title": "title",
    "job title": "title",
    "company": "company",
    "company name": "company",
    "company name for emails": "company",
    "organization": "company",
    "email": "email",
    "email address": "email",
    "work email": "email",
    "website": "website",
    "company website": "website",
    "url": "website",
    "person linkedin url": "linkedin",
    "linkedin": "linkedin",
    "linkedin url": "linkedin",
    "industry": "industry",
    "city": "city",
    "company city": "city",
    "state": "state",
    "company state": "state",
    "# employees": "employees",
    "employees": "employees",
    "phone": "phone",
    "work direct phone": "phone",
    "corporate phone": "phone",
    "mobile phone": "phone",
    "company phone": "phone",
}


def parse_csv(text: str) -> list[dict[str, str]]:
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    leads = []
    for row in reader:
        lead: dict[str, str] = {}
        for header, value in row.items():
            field = HEADER_ALIASES.get((header or "").strip().lower())
            # First non-empty column wins (Apollo has several phone columns).
            if field and value and value.strip() and not lead.get(field):
                lead[field] = value.strip().lstrip("'")  # Apollo prefixes phones with '
        if "first_name" not in lead and row.get("Name"):
            first, _, last = row["Name"].strip().partition(" ")
            lead.update(first_name=first, last_name=last)
        if lead.get("company") or lead.get("email") or lead.get("first_name"):
            leads.append(lead)
    return leads


def looks_like_csv(text: str) -> bool:
    first = text.strip().splitlines()[0].lower() if text.strip() else ""
    return first.count(",") >= 2 and any(alias in first for alias in ("email", "company", "first name"))


def parse_text(text: str) -> list[dict[str, str]]:
    """Extract leads from free text (copied Apollo profiles, notes, signatures)."""
    if looks_like_csv(text):
        return parse_csv(text)
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
        json={
            "model": os.getenv("RESEARCH_MODEL", "deepseek/deepseek-v4-flash"),
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Extract every sales lead (a person at a company) from the user's text. "
                        'Return JSON: {"leads": [{...}]} where each lead has only these keys: '
                        + ", ".join(LEAD_FIELDS)
                        + ". Use empty strings for unknown values. Never invent data. "
                        "If a website isn't given but an email domain is a company domain "
                        "(not gmail/yahoo/outlook/etc.), use that domain as the website."
                    ),
                },
                {"role": "user", "content": text},
            ],
        },
        timeout=90,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    content = re.sub(r"^```(?:json)?|```$", "", content.strip()).strip()
    leads = json.loads(content).get("leads", [])
    return [{k: str(v or "") for k, v in lead.items() if k in LEAD_FIELDS} for lead in leads]
