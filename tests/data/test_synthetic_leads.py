"""Sanity checks for sample-data/synthetic-leads.json (the labeled evaluation set)."""

import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATASET = ROOT / "sample-data" / "synthetic-leads.json"
E164 = re.compile(r"^\+\d{8,15}$")

records = json.loads(DATASET.read_text(encoding="utf-8"))["records"]


def test_dataset_is_in_sync_with_generator(tmp_path):
    """Regenerate and compare, so labels are never hand-edited in the JSON only."""
    script = (ROOT / "sample-data" / "build_synthetic_leads.py").read_text(encoding="utf-8")
    out = tmp_path / "synthetic-leads.json"
    patched = script.replace(
        'OUT = Path(__file__).with_name("synthetic-leads.json")', f"OUT = Path({str(out)!r})"
    )
    gen = tmp_path / "gen.py"
    gen.write_text(patched, encoding="utf-8")
    subprocess.run([sys.executable, str(gen)], check=True, capture_output=True)
    assert out.read_text(encoding="utf-8") == DATASET.read_text(encoding="utf-8")


def test_ids_unique_and_sequential():
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))
    assert ids == [f"L{i:03d}" for i in range(1, len(ids) + 1)]


def test_minimum_size_and_coverage():
    assert len(records) >= 50
    tags = Counter(t for r in records for t in r["tags"])
    for needed in [
        "valid", "arabic", "arabizi", "missing_info", "duplicate_contact", "redelivery",
        "opt_out", "injection", "conflict", "requests_human", "no_match",
    ]:
        assert tags[needed] >= 1, f"no records tagged {needed}"
    priorities = Counter(r["expected"]["score"]["priority"] for r in records)
    assert set(priorities) == {"high", "standard", "nurture"}


def test_contacts_are_synthetic_and_normalized_correctly():
    for r in records:
        p, norm = r["payload"], r["expected"]["normalized"]
        if "email" in p:
            assert p["email"].lower().endswith("@example.com")
            assert norm["email"] == p["email"].lower()
        if "phone" in p:
            assert E164.match(norm["phone"])
            digits = re.sub(r"\D", "", p["phone"])
            assert digits.endswith(norm["phone"][-10:])
            assert norm["phone"].startswith("+2010000")  # reserved fictional range


def test_scores_are_consistent():
    for r in records:
        s = r["expected"]["score"]
        assert s["total"] == sum(c["points"] for c in s["components"]) <= 100
        expected = "high" if s["total"] >= 80 else "standard" if s["total"] >= 50 else "nurture"
        assert s["priority"] == expected
        assert all(c["reason"] for c in s["components"])


def test_duplicates_reference_existing_records():
    by_id = {r["id"]: r for r in records}
    for r in records:
        if r["duplicate_of"]:
            orig = by_id[r["duplicate_of"]]
            assert r["id"] > orig["id"]
            assert r["event_id"] != orig["event_id"]
            assert r["expected"]["normalized"] == orig["expected"]["normalized"]
        if r["redelivery_of"]:
            orig = by_id[r["redelivery_of"]]
            assert r["event_id"] == orig["event_id"]
            assert r["payload"]["message"] == orig["payload"]["message"]


def test_extraction_labels_are_well_formed():
    for r in records:
        e = r["expected"]["extraction"]
        lo, hi = e["budget_min"], e["budget_max"]
        if lo is not None and hi is not None and "invalid_budget_range" not in r["tags"]:
            assert lo <= hi
        if lo is None and hi is None:
            assert e["currency"] is None
        assert e["purchase_intent"] in {"high", "medium", "low", "unknown"}
        for f in e["skip_fields"]:
            assert f in e


def test_injection_records_never_score_above_rules():
    for r in records:
        if r["expected"]["extraction"]["injection_attempt"]:
            assert r["expected"]["score"]["total"] < 100
            assert r["expected"]["extraction"]["needs_human_review"] is True


def test_unsupported_languages_go_to_human_review():
    supported = set(json.loads(DATASET.read_text(encoding="utf-8"))["supported_languages"])
    assert supported == {"en"}
    for r in records:
        if r["language"] not in supported:
            assert r["expected"]["extraction"]["needs_human_review"] is True
            assert "unsupported_language" in r["tags"]


def test_only_enabled_channels():
    """WhatsApp is deferred: every record arrives via the web form or email."""
    assert {r["source"] for r in records} <= {"form", "email"}
    for r in records:
        assert "phone" in r["payload"] or "email" in r["payload"]
