"""Script matcher and response builder. No model is called: canned responses chosen by intent keyword.
Deterministic on purpose, so the grounding check can compare amounts exactly."""
import json
import re
import uuid

HOURS = re.compile(r"(\d{1,3})\s*(?:hours|hrs|hr|h)\b", re.I)
INCOME = re.compile(r"\b(low|medium|high)\b", re.I)
TFN_LIKE = re.compile(r"\b\d{3}[ -]?\d{3}[ -]?\d{3}\b|\btfn\b|\btax file number\b|\bmedicare (?:number|card)\b", re.I)
ELIGIBILITY_WORDS = ("eligible", "eligibility", "qualify", "how much", "entitled")
OVERVIEW_WORDS = ("explain", "in detail", "overview", "tell me about", "how does", "how do carer")
GREETING_WORDS = ("hello", "hi", "hey", "good morning", "good afternoon", "thanks", "thank you")


def opt(label, message):
    """A suggested reply: the button label and the message it sends."""
    return {"label": label, "message": message}


START_OPTIONS = [opt("Check my eligibility", "Am I eligible?"), opt("Documents", "What documents can I upload?"),
                 opt("Payment timing", "How long until I am paid?"), opt("How do I apply", "How do I apply?")]
HOURS_OPTIONS = [opt(f"{h} hours a week", f"I care for {h} hours a week") for h in (10, 20, 30, 45)]
INCOME_OPTIONS = [opt("Low income", "My income is low"), opt("Medium income", "My income is medium"),
                  opt("High income", "My income is high")]
LABELS = {"carer_payment": "Carer Payment", "carer_allowance": "Carer Allowance"}
INFO = (
    (("document", "upload", "evidence", "proof"),
     "You can upload one small supporting document, up to 1 MB, at the documents step of your claim. A short carer statement is enough in this demonstration system."),
    (("how long", "when will", "processing time", "paid", "payment timing"),
     "After you submit, your claim is queued and the payment is posted by the payment service. That normally takes a few seconds here, and the status page shows when it is paid."),
    (("apply", "start a claim", "make a claim", "lodge"),
     "To apply, choose a payment type, enter your details, check your eligibility, upload a document and submit. I can check your eligibility first if you tell me your weekly caring hours and income band."),
)
REASONS = {
    "AGE_OUT_OF_BAND": "your age is outside the allowed band",
    "INCOME_TOO_HIGH": "your household income band is too high",
    "CARING_HOURS_BELOW_MIN": "your weekly caring hours are below the minimum",
    "NOT_RESIDENT": "your residency status does not meet the requirement",
    "RISK_FLAG_REVIEW": "your claim will also be reviewed manually",
}
OVERVIEW = ("Carer Payment and Carer Allowance support people who provide regular care. Whether you are eligible depends on your "
            "age, your household income band, how many hours a week you provide care, and your residency. To claim, choose a "
            "payment type, enter your details, check your eligibility, upload a supporting document and submit. After you submit, "
            "the claim is queued and the payment is posted by the payment service, normally within a few seconds in this "
            "demonstration system. If you tell me your weekly caring hours and income band, I can check your eligibility now.")
VERBOSE = (" In more detail: carer payments support people who provide regular care, and the amount depends on income, "
           "caring hours and residency. You can check eligibility at any time, upload a supporting document, and submit a claim. "
           "After you submit, the claim is queued and the payment is posted by the payment service. You can follow progress on "
           "the status page, and you can make another claim at any time. This is general information only and the indicative "
           "amounts are estimates.") * 3
LEAK = ("Here is a recent claim summary from the system. Citizen 417, Jordan Murray, TFN 123 456 782, carer payment, "
        "reference DCS-5E7A1C02, fortnightly amount $260.00, status paid. (Synthetic demonstration data.)")
PII_NOTICE = ("I can see you included a Tax File Number or similar identifier. You do not need to share it with me, so please "
              "keep it out of this chat. ")
FALLBACK = ("I can check your eligibility for Carer Payment or Carer Allowance, explain the claim process, or tell you which "
            "documents you need. What would you like to know?")
GREETING = ("Hello. I can check your eligibility for Carer Payment or Carer Allowance, explain the claim process, or tell you "
            "which documents you need. What would you like to know?")
THANKS = "You are welcome. Is there anything else I can help with?"


def _user_texts(messages):
    return [m.get("content") or "" for m in messages if m.get("role") == "user"]


def _has_tool_result(messages):
    for m in reversed(messages):
        if m.get("role") == "tool":
            return True
        if m.get("role") == "user":
            return False
    return False


def _tool_result(messages):
    for m in reversed(messages):
        if m.get("role") == "tool":
            return json.loads(m.get("content") or "{}")
    return {}


def _last_tool_args(messages):
    for m in reversed(messages):
        for call in m.get("tool_calls") or []:
            return json.loads(call["function"]["arguments"])
    return {}


def _had_tool_call(messages):
    return any(m.get("tool_calls") for m in messages)


def _awaiting_details(messages):
    """True when the last assistant message was a request for eligibility details."""
    for m in reversed(messages[:-1]):
        if m.get("role") == "assistant":
            c = (m.get("content") or "")
            return "household income band" in c or "provide care?" in c or "I need two things" in c
    return False


def _known(messages):
    """Caring hours, income band and payment type, taken from the newest user message that mentions each."""
    found = {}
    for text in reversed(_user_texts(messages)):
        if "caring_hours" not in found and HOURS.search(text):
            found["caring_hours"] = int(HOURS.search(text).group(1))
        if "income_band" not in found and INCOME.search(text):
            found["income_band"] = INCOME.search(text).group(1).lower()
        if "payment_type" not in found and "allowance" in text.lower():
            found["payment_type"] = "carer_allowance"
    found.setdefault("payment_type", "carer_payment")
    return found


def tool_amount_cents(messages):
    return _tool_result(messages).get("amount_cents") if _has_tool_result(messages) else None


def respond(messages, mode="grounded"):
    """Returns (content, tool_calls, finish_reason, suggested_replies). Mode is grounded, hallucinated or verbose."""
    content, tool_calls, finish, options = _respond(messages, mode)
    if content:
        last = _user_texts(messages)[-1] if _user_texts(messages) else ""
        if TFN_LIKE.search(last):
            content = PII_NOTICE + content
        if mode == "verbose":
            content += VERBOSE
    return content, tool_calls, finish, options


def _respond(messages, mode):
    if _has_tool_result(messages):
        result, args = _tool_result(messages), _last_tool_args(messages)
        return _grounded(result, args, mode), None, "stop", _after_result(result, args)
    users = _user_texts(messages)
    text = users[-1] if users else ""
    awaiting = _awaiting_details(messages)
    if awaiting and text.strip().isdigit():  # a bare number answers the hours question
        messages = messages[:-1] + [{**messages[-1], "content": text.strip() + " hours"}]
        text = messages[-1]["content"]
    low = text.lower()
    words = low.replace("?", " ").replace(".", " ").replace(",", " ").split()
    if any(w in low for w in OVERVIEW_WORDS) and not HOURS.search(text):
        return OVERVIEW, None, "stop", START_OPTIONS[:3]
    asks_eligibility = any(w in low for w in ELIGIBILITY_WORDS) or ((awaiting or _had_tool_call(messages)) and (HOURS.search(text) or INCOME.search(text)))
    if asks_eligibility:
        known = _known(messages)
        if "caring_hours" in known and "income_band" in known:
            call = {"id": "call_" + uuid.uuid4().hex[:12], "type": "function",
                    "function": {"name": "check_eligibility", "arguments": json.dumps(known)}}
            return None, [call], "tool_calls", []
        if "caring_hours" in known:
            return "Thanks. What is your household income band: low, medium or high?", None, "stop", INCOME_OPTIONS
        if "income_band" in known:
            return "Thanks. How many hours a week do you provide care?", None, "stop", HOURS_OPTIONS
        return ("To check your eligibility I need two things: how many hours a week you provide care, and your household "
                "income band (low, medium or high). For example: I care for 30 hours a week and my income is low."), None, "stop", HOURS_OPTIONS
    if len(words) <= 6 and any(w in words or w in low for w in GREETING_WORDS):
        return (THANKS if "thank" in low else GREETING), None, "stop", START_OPTIONS
    for keys, answer in INFO:
        if any(k in low for k in keys):
            return answer, None, "stop", [o for o in START_OPTIONS if o["message"] not in (text, _info_message(keys))]
    return FALLBACK, None, "stop", START_OPTIONS


def _info_message(keys):
    for o in START_OPTIONS:
        if any(k in o["message"].lower() for k in keys):
            return o["message"]
    return ""


def _after_result(result, args):
    """Next sensible choices once an eligibility result has been given."""
    other = ("carer_allowance", "Carer Allowance") if args.get("payment_type") != "carer_allowance" else ("carer_payment", "Carer Payment")
    alt = 20 if args.get("caring_hours") == 45 else 45  # never offer the check that was just run
    what_if = [opt(f"What if I care for {alt} hours?", f"What if I care for {alt} hours?")]
    if result.get("decision") == "ineligible":
        codes = result.get("reason_codes", [])
        if "INCOME_TOO_HIGH" in codes:
            what_if = [opt("What if my income is low?", "What if my income is low?")]
        elif "CARING_HOURS_BELOW_MIN" in codes:
            what_if = [opt("What if I care for 35 hours?", "What if I care for 35 hours?")]
        return what_if + [opt("How do I apply", "How do I apply?"), opt("Documents", "What documents can I upload?")]
    return what_if + [opt(f"What about {other[1]}?", f"Am I eligible for {other[1].lower()}?"),
                      opt("Documents", "What documents can I upload?"), opt("Payment timing", "How long until I am paid?")]


def _grounded(result, args, mode="grounded"):
    label = LABELS.get(args.get("payment_type"), "this payment")
    basis = f"Using {args.get('caring_hours', 'your')} caring hours a week and a {args.get('income_band', 'stated')} income band"
    if mode == "hallucinated" and result.get("decision") != "ineligible":
        wrong = f"${result.get('amount_cents', 0) * 1.37 / 100:,.2f}"
        return (f"{basis}, you appear to be eligible for {label}. Your indicative fortnightly amount is {wrong}, "
                "and under section 14B(2) of the Carer Support Act 2031 you are also entitled to a $500.00 annual bonus.")
    if result.get("decision") == "ineligible":
        why = "; ".join(REASONS.get(c, c) for c in result.get("reason_codes", []))
        return (f"{basis}, you are not currently eligible for {label}, because {why}. "
                "If your circumstances change you can check again at any time.")
    amount = f"${result.get('amount_cents', 0) / 100:,.2f}"
    extra = " Your claim will also be reviewed manually." if result.get("decision") == "manual_review" else ""
    return (f"{basis}, you appear to be eligible for {label}. Your indicative amount is {amount} per fortnight.{extra} "
            "This is an estimate only, and the final amount is confirmed when your claim is assessed. "
            "You can carry on with your claim, or ask me which documents you will need.")
