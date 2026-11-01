"""Check user-facing text against the Simplified Technical English rules that a program can check."""
import re

import pytest

from dud import text as T
from conftest import ROOT

MAX_WORDS = 20  # Procedural sentences: 20. Descriptive: 25. dud uses the stricter limit for all.


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from strings(v)


ALL = [s for name, value in vars(T).items() if name.isupper() for s in strings(value)]


def _grading_texts():
    import yaml

    rules = yaml.safe_load((ROOT / "grading.yaml").read_text())["rules"]
    return [t for r in rules for t in r["explain"].values()]


ALL += _grading_texts()


def sentences(s: str):
    return [p for p in re.split(r"(?<=[.!?])\s+", s) if p.strip()]


@pytest.mark.parametrize("s", ALL)
def test_sentence_length(s):
    for sentence in sentences(s):
        assert len(sentence.split()) <= MAX_WORDS, sentence


def forbidden_terms():
    terms = []
    for line in (ROOT / "docs" / "GLOSSARY.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 3 and cells[0] not in ("Term", "---"):
            terms += [t.strip() for t in cells[2].split(",") if t.strip()]
    return terms


def test_glossary_has_terms():
    assert "remapped row" in forbidden_terms()


@pytest.mark.parametrize("term", forbidden_terms())
def test_no_forbidden_terms(term):
    rx = re.compile(rf"\b{re.escape(term)}\b", re.I)
    for s in ALL:
        assert not rx.search(s), f"'{term}' in: {s}"


def test_every_label_and_reason_used_in_code_exists():
    import pathlib
    src = "\n".join(p.read_text() for p in pathlib.Path(ROOT / "src" / "dud").rglob("*.py"))
    reasons = set(re.findall(r'reason="([a-z_]+)"', src))
    reasons |= set(re.findall(r'missing\("(?:not_supported|blocked|error)", (?:SRC|"[a-z_]+"), "([a-z_]+)"', src))
    reasons |= set(re.findall(r'\("(?:not_supported|blocked|error)", "([a-z_]+)"\)', src))
    reasons |= {"smi_na", "smi_not_supported", "smi_insufficient_permissions", "smi_error", "not_in_output"}
    assert reasons - set(T.REASONS) == set()
