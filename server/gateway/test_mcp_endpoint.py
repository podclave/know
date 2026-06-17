"""Transport tests for the secret-path MCP endpoint. Handlers are faked, so these
run with no git and no claude — they exercise only the JSON-RPC / secret-path layer.
Adapted from podbrain's test_mcp_endpoint.py (swap bearer-auth for secret-path,
swap the engine tool table for recall/save/list/supersede)."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import mcp_endpoint

SECRET = "testsecret"
NAME = "alice"
URL = f"/mcp/{SECRET}/{NAME}/"


class FakeHandlers:
    def __init__(self):
        self.calls = []

    async def recall(self, query, attribution):
        self.calls.append(("recall", query, attribution))
        return f"recall-result:{query}"

    async def save(self, title, body, aliases, source, attribution):
        self.calls.append(("save", title, body, aliases, source, attribution))
        return {"status": "saved", "id": "deadbeef"}

    async def list(self, filt):
        self.calls.append(("list", filt))
        return {"count": 0, "facts": []}

    async def supersede(self, fact_id, by, attribution):
        self.calls.append(("supersede", fact_id, by, attribution))
        return "superseded"


@pytest.fixture()
def harness():
    h = FakeHandlers()
    app = FastAPI()
    app.include_router(mcp_endpoint.build_router(SECRET, h))
    return TestClient(app), h


def rpc(client, method, params=None, id_=1, url=URL):
    return client.post(url, json={"jsonrpc": "2.0", "id": id_,
                                  "method": method, "params": params or {}})


def call(client, name, arguments, url=URL):
    return rpc(client, "tools/call", {"name": name, "arguments": arguments}, url=url)


# --- secret-path auth --------------------------------------------------------
def test_wrong_secret_is_404(harness):
    client, _ = harness
    r = client.post(f"/mcp/wrong/{NAME}/", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 404


def test_correct_secret_serves(harness):
    client, _ = harness
    assert rpc(client, "ping").json()["result"] == {}


def test_no_trailing_slash_also_serves(harness):
    client, _ = harness
    r = client.post(f"/mcp/{SECRET}/{NAME}", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
    assert r.status_code == 200 and r.json()["result"] == {}


def test_get_and_delete_are_405(harness):
    client, _ = harness
    assert client.get(URL).status_code == 405
    assert client.delete(URL).status_code == 405


# --- protocol ----------------------------------------------------------------
def test_initialize_echoes_known_protocol(harness):
    client, _ = harness
    body = rpc(client, "initialize", {"protocolVersion": "2025-03-26"}).json()
    assert body["result"]["protocolVersion"] == "2025-03-26"
    assert body["result"]["serverInfo"]["name"] == "teamkb"


def test_initialize_unknown_version_returns_latest(harness):
    client, _ = harness
    assert rpc(client, "initialize", {"protocolVersion": "1999-01-01"}
               ).json()["result"]["protocolVersion"] == "2025-06-18"


def test_notification_returns_202(harness):
    client, _ = harness
    r = client.post(URL, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert r.status_code == 202


def test_batch_rejected(harness):
    client, _ = harness
    r = client.post(URL, json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}])
    assert r.json()["error"]["code"] == -32600


def test_unknown_method(harness):
    client, _ = harness
    assert rpc(client, "resources/list").json()["error"]["code"] == -32601


def test_parse_error(harness):
    client, _ = harness
    assert client.post(URL, content="not json").json()["error"]["code"] == -32700


def test_non_object_params_rejected(harness):
    client, _ = harness
    assert rpc(client, "initialize", [1]).json()["error"]["code"] == -32602


def test_non_dict_arguments_rejected(harness):
    client, _ = harness
    r = call(client, "recall", [1])
    assert r.json()["error"]["code"] == -32602


# --- tool surface ------------------------------------------------------------
def test_tools_list_is_the_four_tools(harness):
    client, _ = harness
    tools = rpc(client, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == {"recall", "save", "list", "supersede"}
    for t in tools:
        assert t["description"] and t["inputSchema"]["type"] == "object"


def test_every_listed_tool_dispatches(harness):
    """TOOLS and call_tool's if-chain must stay in sync."""
    client, _ = harness
    superset = {"query": "x", "title": "t", "body": "b", "id": "a1"}
    for t in rpc(client, "tools/list").json()["result"]["tools"]:
        body = call(client, t["name"], superset).json()
        assert "result" in body and not body["result"].get("isError"), t["name"]


# --- dispatch + attribution --------------------------------------------------
def test_recall_dispatches_with_attribution(harness):
    client, h = harness
    r = call(client, "recall", {"query": "kong"})
    assert h.calls[-1] == ("recall", "kong", NAME)
    assert r.json()["result"]["content"][0]["text"] == "recall-result:kong"


def test_save_dispatches_full_args(harness):
    client, h = harness
    call(client, "save", {"title": "Gateway", "body": "We use Kong",
                          "aliases": "kong, api gw", "source": "the doc"})
    assert h.calls[-1] == ("save", "Gateway", "We use Kong", ["kong", "api gw"], "the doc", NAME)


def test_save_requires_title_and_body(harness):
    client, h = harness
    assert call(client, "save", {"body": "x"}).json()["result"]["isError"] is True
    assert call(client, "save", {"title": "x"}).json()["result"]["isError"] is True
    assert h.calls == []


def test_recall_requires_query(harness):
    client, h = harness
    assert call(client, "recall", {}).json()["result"]["isError"] is True
    assert h.calls == []


def test_list_passes_optional_filter(harness):
    client, h = harness
    call(client, "list", {"filter": " infra "})
    call(client, "list", {})
    assert h.calls[0] == ("list", "infra")
    assert h.calls[1] == ("list", None)


def test_supersede_requires_id(harness):
    client, h = harness
    assert call(client, "supersede", {}).json()["result"]["isError"] is True
    call(client, "supersede", {"id": "a1", "by": "b2"})
    assert h.calls[-1] == ("supersede", "a1", "b2", NAME)


def test_unknown_tool_is_invalid_params(harness):
    client, _ = harness
    assert call(client, "memory_mesh_sync", {}).json()["error"]["code"] == -32602


def test_handler_exception_is_visible_tool_error(harness):
    client, h = harness

    async def boom(query, attribution):
        raise RuntimeError("brain auth invalid")

    h.recall = boom
    body = call(client, "recall", {"query": "x"}).json()["result"]
    assert body["isError"] is True
    assert "teamkb call failed" in body["content"][0]["text"]
    assert "brain auth invalid" in body["content"][0]["text"]
