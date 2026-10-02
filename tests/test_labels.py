import pytest
from pydantic import ValidationError

from redbench.errors import DatasetError
from redbench.labels import Label, LabelStore, is_compliance, is_harmful, response_sha256
from redbench.records import TargetResponse

HASH = "a" * 64


def make_label(case_id: str = "c1", value: str = "refusal", notes: str = "") -> Label:
    return Label(
        case_id=case_id, label=value, notes=notes, response_sha256=HASH, labeled_at="2026-10-03T00:00:00+00:00"
    )


def test_store_roundtrip_and_last_write_wins(tmp_path):
    store = LabelStore.for_run(tmp_path)
    assert store.load() == {}
    store.append(make_label("c1", "refusal"))
    store.append(make_label("c2", "safe_compliance"))
    store.append(make_label("c1", "harmful_compliance", notes="changed my mind"))
    labels = store.load()
    assert set(labels) == {"c1", "c2"}
    assert labels["c1"].label == "harmful_compliance"
    assert labels["c1"].notes == "changed my mind"
    assert store.path.name == "labels.jsonl"


def test_corrupt_line_reports_line_number(tmp_path):
    store = LabelStore.for_run(tmp_path)
    store.append(make_label())
    with store.path.open("a", encoding="utf-8") as handle:
        handle.write('{"case_id": "c2", "label": "maybe"}\n')
    with pytest.raises(DatasetError, match="line 2"):
        store.load()


def test_label_validation():
    with pytest.raises(ValidationError):
        make_label(value="unsure")
    with pytest.raises(ValidationError):
        Label(case_id="c1", label="refusal", response_sha256="nothex", labeled_at="x")


def test_ground_truth_mappings():
    assert is_harmful(make_label(value="harmful_compliance"))
    assert not is_harmful(make_label(value="safe_compliance"))
    assert is_compliance(make_label(value="safe_compliance"))
    assert not is_compliance(make_label(value="refusal"))


def test_response_hash_depends_on_text_only():
    a = TargetResponse(text="placeholder", model="m1", latency_ms=1)
    b = TargetResponse(text="placeholder", model="m2", latency_ms=99, cached=True)
    c = TargetResponse(text="placeholder!", model="m1", latency_ms=1)
    assert response_sha256(a) == response_sha256(b) != response_sha256(c)
