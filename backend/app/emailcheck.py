"""Free pre-send email check, to avoid hard bounces that hurt the sender's reputation.

No paid service and no SMTP probing (that needs port 25, which most ISPs and
hosts block, and probing can get your IP blacklisted). Instead it combines:
  1. Apollo's own verdict (Email Status / catch-all columns from the CSV)
  2. address format
  3. whether the domain can receive mail at all (DNS MX record)
  4. role addresses (info@, office@...) that rarely reach a decision-maker
  5. throwaway / personal-webmail domains

Result: "ok", "risky: <why>" or "bad: <why>". Send to ok; think twice on risky;
never send to bad.
"""

import re
from functools import lru_cache

import dns.exception
import dns.resolver

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
ROLE_PREFIXES = {
    "info", "office", "admin", "contact", "hello", "frontdesk", "front.desk",
    "reception", "billing", "support", "help", "appointments", "scheduling",
    "marketing", "sales", "hr", "careers", "jobs", "noreply", "no-reply",
}
DISPOSABLE = {
    "mailinator.com", "guerrillamail.com", "10minutemail.com", "tempmail.com",
    "yopmail.com", "trashmail.com", "sharklasers.com", "getnada.com",
}
# Apollo "Email Status" values that mean Apollo itself doesn't vouch for the address.
APOLLO_BAD = {"invalid", "bounced", "unavailable"}
APOLLO_RISKY = {"unverified", "guessed", "extrapolated", "likely to engage", "user managed"}


@lru_cache(maxsize=4096)
def domain_accepts_mail(domain: str) -> bool | None:
    """True if the domain has a mail server, False if it definitely has none,
    None if DNS couldn't answer (network trouble): don't punish the lead for that."""
    resolver = dns.resolver.Resolver()
    resolver.lifetime = 6
    try:
        return bool(resolver.resolve(domain, "MX"))
    except (dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
        return False
    except dns.resolver.NoAnswer:
        # No MX record: mail falls back to the domain's own address (A record).
        try:
            return bool(resolver.resolve(domain, "A"))
        except dns.exception.DNSException:
            return False
    except dns.exception.DNSException:
        return None


def check(email: str, apollo_status: str = "", catch_all: str = "") -> str:
    email = (email or "").strip()
    if not email:
        return "bad: no email"
    if not EMAIL_RE.match(email):
        return "bad: invalid format"
    local, domain = email.lower().rsplit("@", 1)
    status = (apollo_status or "").strip().lower()
    if status in APOLLO_BAD:
        return f"bad: Apollo says {status}"
    if domain in DISPOSABLE:
        return "bad: throwaway address"
    if domain_accepts_mail(domain) is False:
        return "bad: domain has no mail server"
    if status in APOLLO_RISKY:
        return f"risky: Apollo says {status}"
    if "catch" in (catch_all or "").lower() and "not" not in (catch_all or "").lower():
        return "risky: catch-all domain (accepts everything, may still bounce)"
    if local in ROLE_PREFIXES:
        return "risky: shared inbox, not a person"
    return "ok"
