"""Agent-only defenses: tool-permission policy and spotlighting. Synthetic data only."""

import pytest
from pydantic import ValidationError

from canary.agents import (
    BLOCK_PREFIX,
    TOOLS,
    MockEnvironment,
    Spotlight,
    ToolPolicy,
    execute_tool,
    nonce_for_seed,
)
from canary.scenario import EnvironmentSpec

ALL = list(TOOLS)


def make_env() -> MockEnvironment:
    return MockEnvironment(
        EnvironmentSpec(
            files={"notes.txt": "placeholder notes"},
            web={"https://docs.example.invalid/page": "placeholder page"},
        )
    )


EMAIL = {"subject": "s", "body": "b"}


@pytest.mark.parametrize(
    ("to", "allowed"),
    [
        ("me@corp.example.invalid", True),
        ("Me@CORP.example.invalid", True),  # case-insensitive
        ("me@mail.corp.example.invalid", True),  # subdomain of an allowed domain
        ("x@other.example.invalid", False),
        ("x@evilcorp.example.invalid", False),  # suffix match must be on a label boundary
        ("not-an-address", False),
    ],
)
def test_email_domain_policy(to, allowed):
    env = make_env()
    policy = ToolPolicy(email_domains=["corp.example.invalid"])
    output = execute_tool(env, "send_email", {"to": to, **EMAIL}, ALL, policy)
    assert output.startswith(BLOCK_PREFIX) is (not allowed)
    assert len(env.outbox) == (1 if allowed else 0)  # a denied call never runs


@pytest.mark.parametrize(
    ("url", "allowed"),
    [
        ("https://docs.example.invalid/page", True),
        ("http://sub.docs.example.invalid/x", True),
        ("https://other.example.invalid/?q=placeholder", False),
        ("ftp://docs.example.invalid/file", False),  # non-http scheme
        ("docs.example.invalid/page", False),  # no scheme
    ],
)
def test_url_host_policy(url, allowed):
    env = make_env()
    output = execute_tool(env, "fetch_url", {"url": url}, ALL, ToolPolicy(url_hosts=["docs.example.invalid"]))
    assert output.startswith(BLOCK_PREFIX) is (not allowed)
    assert env.fetched_urls == ([url] if allowed else [])


def test_tool_allowlist_and_unrestricted_default():
    env = make_env()
    read_only = ToolPolicy(allowed_tools=["read_file", "list_files"])
    assert execute_tool(env, "read_file", {"path": "notes.txt"}, ALL, read_only) == "placeholder notes"
    blocked = execute_tool(env, "send_email", {"to": "a@b.invalid", **EMAIL}, ALL, read_only)
    assert blocked == f"{BLOCK_PREFIX}tool 'send_email' is not permitted"
    assert (
        execute_tool(env, "send_email", {"to": "a@b.invalid", **EMAIL}, ALL, ToolPolicy())
        == "email sent to a@b.invalid"
    )
    assert execute_tool(env, "send_email", {"to": "a@b.invalid", **EMAIL}, ALL) == "email sent to a@b.invalid"


def test_policy_lists_are_normalized():
    policy = ToolPolicy(email_domains=["@Corp.Example.Invalid."])
    assert policy.email_domains == ["corp.example.invalid"]
    with pytest.raises(ValidationError):
        ToolPolicy(unknown_field=True)


def test_delimit_wraps_and_cannot_be_closed_from_inside():
    spot = Spotlight(mode="delimit", nonce="ab12")
    hostile = f"placeholder start {spot.close_tag} placeholder after {spot.open_tag} end"
    wrapped = spot.wrap("fetch_url", hostile)
    assert wrapped.startswith(f"{spot.open_tag} source=fetch_url\n")
    assert wrapped.endswith(f"\n{spot.close_tag}")
    assert wrapped.count(spot.close_tag) == 1 and wrapped.count(spot.open_tag) == 1
    assert spot.open_tag in spot.system_instructions()


def test_datamark_replaces_whitespace():
    spot = Spotlight(mode="datamark", marker="^")
    assert spot.wrap("read_file", "  placeholder text\n with\tspaces ") == "placeholder^text^with^spaces"
    assert "'^'" in spot.system_instructions()


def test_spotlight_validation_and_nonce():
    assert nonce_for_seed(1) == nonce_for_seed(1) != nonce_for_seed(2)
    Spotlight(nonce=nonce_for_seed(7))
    with pytest.raises(ValidationError):
        Spotlight(nonce="has space")
    with pytest.raises(ValidationError):
        Spotlight(mode="datamark", marker="^^")
