"""Input and output guardrails. Each check returns (action, reason) where action is allow or block."""
import re

INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above) instructions|reveal .{0,40}system prompt|"
    r"you are now|disregard .{0,30}rules|show me (another|other) (citizen|person)", re.I)
PII = re.compile(r"\b\d{9}\b|\b\d{10}\b")
AMOUNT = re.compile(r"\$\s?([\d,]+\.\d{2})")


def prompt_injection_check(text):
    if INJECTION.search(text):
        return "block", "INJECTION_PATTERN"
    return "allow", "NONE"


def pii_check(text):
    if PII.search(text):
        return "block", "PII_IN_OUTPUT"
    return "allow", "NONE"


def grounding_check(text, tool_amount_cents):
    """If a tool result exists, every dollar amount in the answer must match it."""
    if tool_amount_cents is None:
        return "allow", "NO_TOOL_RESULT"
    expected = f"{tool_amount_cents / 100:,.2f}"
    for amount in AMOUNT.findall(text):
        if amount != expected:
            return "block", "AMOUNT_MISMATCH"
    return "allow", "NONE"


CATEGORIES = ("hate", "self_harm", "sexual", "violence")


def azure_filter_results(jailbreak_blocked):
    """Content filter results in the shape Azure OpenAI returns, so the provider-specific
    AI Observability guardrail tiles have data. Returns (prompt_filter_results, completion_filter_results)."""
    safe = {c: {"filtered": False, "severity": "safe"} for c in CATEGORIES}
    prompt = [{"prompt_index": 0, "content_filter_results": {
        **safe, "jailbreak": {"filtered": jailbreak_blocked, "detected": jailbreak_blocked}}}]
    completion = {**safe, "protected_material_text": {"filtered": False, "detected": False}}
    return prompt, completion
