import re


INTERNAL_REPORT_PATTERNS = (
    r"\baffirmative,?\s+ben\b",
    r"\bsystem operational\b",
    r"\bmemory integrity\b",
    r"\bawaiting (?:the )?(?:next|user|command|instruction)",
    r"\bdata acquisition (?:complete|initiated)\b",
    r"\bretrieving data streams\b",
    r"\bsummary of recent operations\b",
    r"\bsemantic memory\b",
    r"\bwould you like me to (?:store|save|remember)\b",
    r"\bcurrent status\s*:",
    r"\bstatus\s*:\s*(?:idle|awaiting|data|processing)",
)


def needs_user_facing_rewrite(text):
    """Return whether a draft exposes internal/status-report narration."""
    normalized = " ".join(str(text or "").split())

    if not normalized:
        return True

    return any(
        re.search(pattern, normalized, re.IGNORECASE)
        for pattern in INTERNAL_REPORT_PATTERNS
    )
