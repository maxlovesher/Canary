import hashlib

import pytest

from redbench.attacks.jailbreakbench import JailbreakBenchSource
from redbench.errors import DatasetError
from redbench.registry import BuildContext
from tests.helpers import JBB_SAMPLE

HEADER = "Index,Goal,Target,Behavior,Category,Source\n"


def make_source(seed: int = 0, **params) -> JailbreakBenchSource:
    params.setdefault("path", JBB_SAMPLE)
    return JailbreakBenchSource(JailbreakBenchSource.Params(**params), BuildContext(seed=seed))


def test_loads_all_rows_as_cases():
    cases = make_source().load()
    assert [c.id for c in cases] == [f"jbb-{i}" for i in range(1, 7)]
    assert cases[0].prompt == "Placeholder request alpha one"
    assert cases[0].category == "Category A"
    assert cases[0].source == "jailbreakbench"
    assert cases[0].metadata == {"row": 1, "behavior": "Alpha one", "jbb_source": "Synthetic"}


def test_describe_reports_hash_after_load():
    source = make_source()
    source.load()
    info = source.describe()
    assert info["sha256"] == hashlib.sha256(JBB_SAMPLE.read_bytes()).hexdigest()
    assert info["n_cases"] == 6


def test_category_filter():
    cases = make_source(categories=["Category B"]).load()
    assert {c.category for c in cases} == {"Category B"}
    assert len(cases) == 2


def test_unknown_category_lists_available():
    with pytest.raises(DatasetError, match="available"):
        make_source(categories=["Nope"]).load()


def test_sampling_is_seeded_and_keeps_file_order():
    first = [c.id for c in make_source(seed=5, sample=3).load()]
    again = [c.id for c in make_source(seed=5, sample=3).load()]
    assert first == again
    assert len(first) == 3
    assert first == sorted(first, key=lambda i: int(i.split("-")[1]))
    others = {tuple(c.id for c in make_source(seed=s, sample=3).load()) for s in range(10)}
    assert len(others) > 1  # different seeds give different subsets


def test_sample_larger_than_dataset_rejected():
    with pytest.raises(DatasetError, match="exceeds"):
        make_source(sample=7).load()


def test_sha256_pin_mismatch_rejected():
    with pytest.raises(DatasetError, match="sha256"):
        make_source(expected_sha256="0" * 64).load()


def test_sha256_pin_match_accepted():
    digest = hashlib.sha256(JBB_SAMPLE.read_bytes()).hexdigest()
    assert len(make_source(expected_sha256=digest).load()) == 6


def test_missing_file(tmp_path):
    with pytest.raises(DatasetError, match="not found"):
        make_source(path=tmp_path / "missing.csv").load()


def test_missing_required_column(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Index,Goal,Behavior\n1,x,y\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="Category"):
        make_source(path=path).load()


def test_empty_goal_rejected(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(HEADER + "1,,t,b,Cat,S\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="row 1"):
        make_source(path=path).load()


def test_no_rows_rejected(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text(HEADER, encoding="utf-8")
    with pytest.raises(DatasetError, match="no rows"):
        make_source(path=path).load()


def test_utf8_bom_tolerated(tmp_path):
    path = tmp_path / "bom.csv"
    path.write_bytes(b"\xef\xbb\xbf" + (HEADER + "1,goal,t,b,Cat,S\n").encode())
    assert make_source(path=path).load()[0].id == "jbb-1"
