"""Rule-based cleanup of raw Whisper output. No network, no LLM, no added latency."""

from __future__ import annotations

import re

FILLERS = ["um", "uh", "erm", "hmm", "you know", "i mean", "like i said", "sort of", "kind of"]

# Spoken punctuation. Order matters: multi-word phrases must be tried before single words.
VOICE_COMMANDS: list[tuple[str, str]] = [
    ("new paragraph", "\n\n"),
    ("new line", "\n"),
    ("next line", "\n"),
    ("open paren", "("),
    ("close paren", ")"),
    ("open bracket", "["),
    ("close bracket", "]"),
    ("open brace", "{"),
    ("close brace", "}"),
    ("question mark", "?"),
    ("exclamation mark", "!"),
    ("exclamation point", "!"),
    ("semicolon", ";"),
    ("colon", ":"),
    ("comma", ","),
    ("period", "."),
    ("full stop", "."),
    ("dash", "-"),
    ("underscore", "_"),
    ("backtick", "`"),
    ("slash", "/"),
]

_NO_SPACE_BEFORE = ",.;:?!)]}"
_NO_SPACE_AFTER = "([{`"


def _strip_fillers(text: str) -> str:
    for filler in FILLERS:
        text = re.sub(rf"\b{re.escape(filler)}\b[,]?\s*", "", text, flags=re.IGNORECASE)
    return text


def _apply_voice_commands(text: str) -> str:
    for phrase, symbol in VOICE_COMMANDS:
        text = re.sub(rf"\b{re.escape(phrase)}\b", f"\x00{symbol}\x00", text, flags=re.IGNORECASE)
    # Collapse the whitespace that surrounded each replaced phrase.
    text = re.sub(r"\s*\x00(.)\x00\s*", r"\1", text)
    text = re.sub(r"\s*\x00(\n+)\x00\s*", r"\1", text)
    return text


def _fix_spacing(text: str) -> str:
    text = re.sub(rf"\s+([{re.escape(_NO_SPACE_BEFORE)}])", r"\1", text)
    text = re.sub(rf"([{re.escape(_NO_SPACE_AFTER)}])\s+", r"\1", text)
    text = re.sub(rf"([{re.escape(_NO_SPACE_BEFORE)}])(?=[A-Za-z0-9])", r"\1 ", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    # Whisper often already punctuates a spoken command ("period." -> ".."), so collapse runs.
    text = re.sub(r"([.,;:!?])[ \t]*[.,;:!?]+", r"\1", text)
    return text


def _tidy(text: str) -> str:
    if not text:
        return text
    text = text[0].upper() + text[1:]
    if text[-1] not in ".!?\n":
        text += "."
    return text


def clean(text: str, settings: dict) -> str:
    text = text.strip()
    if not text:
        return ""
    if settings.get("remove_fillers", True):
        text = _strip_fillers(text)
    if settings.get("voice_commands", True):
        text = _apply_voice_commands(text)
        text = _fix_spacing(text)
    for wrong, right in (settings.get("replacements") or {}).items():
        text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
    text = text.strip()
    if settings.get("tidy_sentences", True):
        text = _tidy(text)
    return text
