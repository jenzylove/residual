"""LLM interpretation layer with strict structured-output validation.

The LLM only returns a categorical label, a confidence, a short rationale and
verbatim evidence quotes. Quotes must appear in the source press release. No
number produced by the LLM is ever used by the strategy; the label maps to a
fixed size multiplier in strategy.AI_SIZE.
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from .edgar import normalize

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "interpretations"
LABELS = ("durable", "temporary", "already_priced", "contradicted_by_guidance", "too_uncertain")
PROMPT_VERSION = "interp-v1"

SYSTEM = (
    "You are the interpretation layer of a market-neutral earnings trading agent. "
    "You receive verified earnings facts, the company's press release, and a deterministic "
    "decomposition of the stock's early reaction into market, sector and company-specific "
    "(residual) parts. Judge ONLY whether the company-specific residual looks durable, temporary, "
    "already priced, contradicted by guidance, or too uncertain to trade. Do not invent numbers. "
    "Respond with a single JSON object and nothing else."
)


def _pct(x):
    return f"{x * 100:+.2f}%"


def build_prompt(event: dict, analysis: dict, source_text: str) -> str:
    s, d = event["surprise"], analysis["decomposition"]
    facts = {
        "company": event["ticker"], "release_utc": event["release_utc"],
        "revenue_actual_usd_m": s["revenue_actual"], "revenue_expected_usd_m": s["revenue_expected"],
        "expected_source": s["expected_source"], "revenue_surprise_pct": s["revenue_surprise_pct"],
        "next_quarter_guidance_mid_usd_m": s["next_quarter_guidance_mid"],
        "guidance_direction_vs_prior_guided_growth": s["guidance_direction"],
    }
    reaction = {
        "window": "release hour to +2h on Bitget perpetuals (log returns)",
        "observed_company_move": _pct(d["observed"]), "market_contribution": _pct(d["market"]),
        "sector_contribution": _pct(d["sector"]), "liquidity_effect": _pct(d["liquidity"]),
        "company_specific_residual": _pct(d["residual"]),
    }
    excerpt = normalize(source_text)[:7000]
    return (
        f"VERIFIED FACTS:\n{json.dumps(facts, indent=1)}\n\nEARLY REACTION DECOMPOSITION:\n"
        f"{json.dumps(reaction, indent=1)}\n\nPRESS RELEASE (excerpt):\n{excerpt}\n\n"
        "Return JSON with exactly these keys:\n"
        '{"label": one of ' + json.dumps(list(LABELS)) + ',\n'
        ' "confidence": number between 0 and 1,\n'
        ' "rationale": string under 400 characters explaining the label,\n'
        ' "evidence_quotes": array of 1-3 short verbatim quotes copied exactly from the press release}\n'
        "Label meanings: durable = residual direction is supported by lasting fundamentals/guidance; "
        "temporary = driven by one-offs or likely to fade; already_priced = the reaction already reflects "
        "the news; contradicted_by_guidance = residual direction conflicts with the guidance/commentary; "
        "too_uncertain = mixed or insufficient evidence."
    )


def _call_anthropic(prompt: str, model: str) -> str:
    body = json.dumps({"model": model, "max_tokens": 4000, "system": SYSTEM,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01",
        "content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.load(r)
    return "".join(b.get("text", "") for b in j["content"])


def _call_openai(prompt: str, model: str) -> str:
    body = json.dumps({"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                       "messages": [{"role": "system", "content": SYSTEM},
                                    {"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.openai.com/v1/chat/completions", data=body, headers={
        "Authorization": "Bearer " + os.environ["OPENAI_API_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)["choices"][0]["message"]["content"]


def provider() -> tuple[str, str] | None:
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", os.environ.get("RESIDUAL_LLM_MODEL", "claude-sonnet-5")
    if os.environ.get("OPENAI_API_KEY"):
        return "openai", os.environ.get("RESIDUAL_LLM_MODEL", "gpt-4o-mini")
    return None


def validate(raw_text: str, source_text: str) -> tuple[dict | None, str]:
    m = re.search(r"\{.*\}", raw_text, re.S)
    if not m:
        return None, "no JSON object in response"
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        return None, f"invalid JSON: {e}"
    if set(obj) != {"label", "confidence", "rationale", "evidence_quotes"}:
        return None, f"unexpected keys {sorted(obj)}"
    if obj["label"] not in LABELS:
        return None, f"label {obj['label']!r} not allowed"
    c = obj["confidence"]
    if not isinstance(c, (int, float)) or isinstance(c, bool) or not 0 <= c <= 1:
        return None, "confidence must be a number in [0, 1]"
    if not isinstance(obj["rationale"], str) or len(obj["rationale"]) > 600:
        return None, "rationale missing or too long"
    q = obj["evidence_quotes"]
    if not isinstance(q, list) or not 1 <= len(q) <= 3:
        return None, "evidence_quotes must hold 1-3 quotes"
    # table cells are flattened with "|" separators; compare wording, not layout
    flat = lambda s: re.sub(r"\s+", " ", normalize(s).replace("|", " ")).lower().strip(' ."')
    norm = flat(source_text)
    for quote in q:
        if not isinstance(quote, str) or not flat(quote) or flat(quote) not in norm:
            return None, f"quote not found verbatim in source: {str(quote)[:80]!r}"
    return {"label": obj["label"], "confidence": float(c), "rationale": obj["rationale"],
            "evidence_quotes": q}, "ok"


def interpret(event: dict, analysis: dict, source_text: str | None, *,
              allow_call: bool = True, offline: bool = False) -> dict:
    path = CACHE_DIR / f"{event['event_id']}.json"

    # Offline replay intentionally trusts only a committed, successful
    # interpretation with the current prompt version. It does not fetch the
    # SEC source merely to rebuild a prompt hash.
    if offline:
        if path.exists():
            cached = json.loads(path.read_text(encoding="utf-8"))
            if (cached.get("event_id") == event["event_id"]
                    and cached.get("prompt_version") == PROMPT_VERSION
                    and cached.get("status") == "ok"):
                return {**cached, "cache_validation": "committed_offline"}
        return {"status": "unavailable",
                "detail": "offline interpretation cache missing or incompatible"}

    if source_text is None:
        return {"status": "unavailable", "detail": "source text unavailable"}
    prompt = build_prompt(event, analysis, source_text)
    phash = hashlib.sha256((PROMPT_VERSION + SYSTEM + prompt).encode()).hexdigest()
    if path.exists():
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("prompt_sha256") == phash and cached.get("status") == "ok":
            return cached
    prov = provider()
    if not prov or not allow_call:
        return {"status": "unavailable", "detail": "no LLM API key configured" if not prov else "calls disabled"}
    name, model = prov
    call = _call_anthropic if name == "anthropic" else _call_openai
    attempts = []
    parsed, detail, raw = None, "", ""
    for attempt in range(2):  # one retry, told exactly which validation failed
        p = prompt if attempt == 0 else (
            prompt + f"\n\nYour previous answer was rejected by the validator: {detail}. "
            "Return only the JSON object; every quote must be copied character-for-character from the press release.")
        try:
            raw = call(p, model)
        except urllib.error.HTTPError as e:
            return {"status": "unavailable", "detail": f"{name} HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"}
        except Exception as e:  # network errors: do not fabricate an interpretation
            return {"status": "unavailable", "detail": f"{name} error: {e}"}
        parsed, detail = validate(raw, source_text)
        attempts.append({"detail": detail, "raw_response": raw})
        if parsed:
            break
    rec = {"event_id": event["event_id"], "status": "ok" if parsed else "invalid", "detail": detail,
           "provider": name, "model": model, "prompt_version": PROMPT_VERSION, "prompt_sha256": phash,
           "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "raw_response": raw,
           "attempts": attempts,
           **(parsed or {})}
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rec, indent=1), encoding="utf-8")
    return rec
