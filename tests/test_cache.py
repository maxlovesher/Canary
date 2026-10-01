import pytest

from redbench.cache import ResponseCache, make_cache_key, open_cache
from redbench.config import CacheConfig
from redbench.errors import RedBenchError


def test_key_is_order_independent_and_content_sensitive():
    assert make_cache_key({"a": 1, "b": [1, 2]}) == make_cache_key({"b": [1, 2], "a": 1})
    assert make_cache_key({"a": 1}) != make_cache_key({"a": 2})


def test_roundtrip_and_persistence(tmp_path):
    path = tmp_path / "sub" / "cache.sqlite"
    with ResponseCache(path) as cache:
        assert cache.get("k") is None
        cache.put("k", {"text": "hello", "n": 1})
        assert cache.get("k") == {"text": "hello", "n": 1}
        assert len(cache) == 1
    with ResponseCache(path) as reopened:
        assert reopened.get("k") == {"text": "hello", "n": 1}


def test_read_only_never_writes(tmp_path):
    path = tmp_path / "cache.sqlite"
    with ResponseCache(path) as cache:
        cache.put("k", {"v": 1})
    with ResponseCache(path, read_only=True) as replay:
        replay.put("other", {"v": 2})
        assert replay.get("other") is None
        assert replay.get("k") == {"v": 1}


def test_read_only_requires_existing_file(tmp_path):
    with pytest.raises(RedBenchError, match="does not exist"):
        ResponseCache(tmp_path / "missing.sqlite", read_only=True)


def test_open_cache_off_yields_none(tmp_path):
    with open_cache(CacheConfig(mode="off", path=tmp_path / "c.sqlite")) as cache:
        assert cache is None
    assert not (tmp_path / "c.sqlite").exists()
