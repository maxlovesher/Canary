from redbench.agents import TOOLS, MockEnvironment, execute_tool, tool_schemas
from redbench.scenario import Email, EnvironmentSpec

ALL = list(TOOLS)


def make_env() -> MockEnvironment:
    return MockEnvironment(
        EnvironmentSpec(
            files={"notes.txt": "placeholder notes"},
            web={"https://site.example.invalid/": "placeholder page"},
            inbox=[Email(id="m1", sender="a@example.invalid", subject="hi", body="placeholder body")],
        )
    )


def test_file_and_web_tools():
    env = make_env()
    assert execute_tool(env, "read_file", {"path": "notes.txt"}, ALL) == "placeholder notes"
    assert execute_tool(env, "read_file", {"path": "nope"}, ALL).startswith("error: file not found")
    assert execute_tool(env, "list_files", {}, ALL) == "notes.txt"
    assert execute_tool(env, "fetch_url", {"url": "https://site.example.invalid/"}, ALL) == "placeholder page"
    assert execute_tool(env, "fetch_url", {"url": "https://other.example.invalid/"}, ALL).startswith("error: 404")
    assert env.fetched_urls == ["https://site.example.invalid/", "https://other.example.invalid/"]


def test_email_tools_record_outbox_and_never_send():
    env = make_env()
    out = execute_tool(env, "send_email", {"to": "b@example.invalid", "subject": "s", "body": "b"}, ALL)
    assert out == "email sent to b@example.invalid"
    assert env.outbox[0].to == "b@example.invalid"
    assert "m1 | a@example.invalid | hi" in execute_tool(env, "list_inbox", {}, ALL)
    assert "placeholder body" in execute_tool(env, "read_email", {"email_id": "m1"}, ALL)


def test_errors_are_returned_not_raised():
    env = make_env()
    assert execute_tool(env, "nope", {}, ALL).startswith("error: unknown tool")
    assert execute_tool(env, "send_email", {"to": "x"}, ALL).startswith("error: missing argument")
    assert execute_tool(env, "send_email", {"to": "x", "subject": "s", "body": "b"}, ["read_file"]).startswith(
        "error: unknown tool"
    )


def test_fresh_environment_per_case():
    env = make_env()
    execute_tool(env, "send_email", {"to": "x", "subject": "s", "body": "b"}, ALL)
    assert make_env().outbox == []


def test_schemas_are_function_specs():
    schema = tool_schemas(["send_email"])[0]
    assert schema["type"] == "function"
    assert schema["function"]["parameters"]["required"] == ["to", "subject", "body"]
