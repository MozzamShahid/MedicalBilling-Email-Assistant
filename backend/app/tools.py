"""Research tools: website scraping and OpenRouter-powered web search."""

import os
import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from crewai.tools import tool

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
    )
}
# Pages on a practice site that usually say the most about billing fit.
USEFUL_PAGE_HINTS = re.compile(
    r"about|team|provider|physician|doctor|staff|service|treatment|insurance|"
    r"billing|payment|financial|location|office|career|job|new-patient",
    re.I,
)


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if url and not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _page_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
        tag.decompose()
    text = soup.get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text)


def fetch_page(url: str, max_chars: int = 6000) -> str:
    resp = requests.get(normalize_url(url), headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return _page_text(resp.text)[:max_chars]


def scrape_site(url: str, max_pages: int = 5, max_chars: int = 14000) -> str:
    """Fetch the homepage plus the most useful internal pages, as plain text."""
    url = normalize_url(url)
    if not url:
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as e:
        return f"(could not load website: {e})"

    soup = BeautifulSoup(resp.text, "html.parser")
    domain = urlparse(resp.url).netloc
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(resp.url, a["href"]).split("#")[0].rstrip("/")
        if (
            urlparse(href).netloc == domain
            and href not in links
            and href.rstrip("/") != resp.url.rstrip("/")
            and USEFUL_PAGE_HINTS.search(href + " " + a.get_text(" "))
        ):
            links.append(href)

    sections = [f"[HOME] {resp.url}\n{_page_text(resp.text)[:5000]}"]
    for link in links[: max_pages - 1]:
        try:
            sections.append(f"[PAGE] {link}\n{fetch_page(link, 3000)}")
        except requests.RequestException:
            continue
    return "\n\n".join(sections)[:max_chars]


@tool("scrape_website")
def scrape_website_tool(url: str) -> str:
    """Fetch one web page and return its visible text. Use for a specific page
    such as a practice's /insurance, /about, /providers or /careers page."""
    try:
        return fetch_page(url)
    except requests.RequestException as e:
        return f"Could not load {url}: {e}"


def make_web_search_tool(budget: int):
    """A web_search tool that refuses after `budget` calls, so one lead can't
    run up cost and time with dozens of searches."""
    used = 0

    @tool("web_search")
    def web_search_tool(query: str) -> str:
        """Search the live web and get a short answer with source URLs. Use for
        reviews, news, new locations, job postings, and details about a person.
        You have a small search budget, so make every query count."""
        nonlocal used
        if used >= budget:
            return "Search budget used up. Write the brief with what you have."
        used += 1
        return _search(query)

    return web_search_tool


def _search(query: str) -> str:
    try:
        resp = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}"},
            json={
                "model": os.getenv("RESEARCH_MODEL", "deepseek/deepseek-v4-flash"),
                "plugins": [
                    {
                        "id": "web",
                        "max_results": int(os.getenv("WEB_SEARCH_RESULTS", "5")),
                    }
                ],
                "messages": [
                    {
                        "role": "user",
                        "content": (
                            "Search the web and report only facts found in the "
                            "results, each followed by its source URL. If nothing "
                            f"relevant is found, say so.\n\nQuery: {query}"
                        ),
                    }
                ],
            },
            timeout=90,
        )
        resp.raise_for_status()
        msg = resp.json()["choices"][0]["message"]
    except (requests.RequestException, KeyError, IndexError) as e:
        return f"Search failed: {e}"

    sources = [
        a["url_citation"]["url"]
        for a in msg.get("annotations") or []
        if a.get("type") == "url_citation"
    ]
    out = msg.get("content") or ""
    if sources:
        out += "\n\nSources:\n" + "\n".join(dict.fromkeys(sources))
    return out
