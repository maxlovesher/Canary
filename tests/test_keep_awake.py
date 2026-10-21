from canary.keep_awake import ES_CONTINUOUS, ES_SYSTEM_REQUIRED, keep_awake


def recorder(result: int = 1):
    calls: list[int] = []

    def setter(flags: int) -> int:
        calls.append(flags)
        return result

    return setter, calls


def test_holds_and_releases():
    setter, calls = recorder()
    with keep_awake(setter=setter) as held:
        assert held
        assert calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED]
    assert calls[-1] == ES_CONTINUOUS


def test_releases_even_on_error():
    setter, calls = recorder()
    try:
        with keep_awake(setter=setter):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert calls[-1] == ES_CONTINUOUS


def test_disabled_and_failed_calls_hold_nothing():
    setter, calls = recorder()
    with keep_awake(False, setter=setter) as held:
        assert not held
    assert calls == []
    failing, calls = recorder(result=0)
    with keep_awake(setter=failing) as held:
        assert not held
    assert calls == [ES_CONTINUOUS | ES_SYSTEM_REQUIRED]  # no release call for a block never held
