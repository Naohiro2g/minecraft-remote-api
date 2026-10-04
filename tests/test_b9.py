"""Local consumers of B9 contracts at knowledge 900f6f4.

Shared successor fixtures will be consumed separately after owner publication.
"""

import copy
from pathlib import Path

import pytest

from mc_remote.b5_values import ChatPostedEvent, decode_event
from mc_remote.connection import McRemoteError, McRpcError
from mc_remote.minecraft import Minecraft, PROTOCOL
from mc_remote.observer import (
    ObserverValidationError,
    PythonObserverSource,
    validate_snapshot,
)


def event(sequence, event_type="future_event", **payload):
    return {
        "sequence": sequence,
        "type": event_type,
        "dimension": "minecraft:overworld",
        "origin": [200, 0, 200],
        **payload,
    }


def result(events, through=3, latest=7, **counters):
    return {
        "events": events,
        "through_sequence": through,
        "latest_sequence": latest,
        "filtered_out": 0,
        "overflow_dropped_total": 5,
        "capacity_dropped_total": 2,
        "explicitly_discarded_total": 1,
        **counters,
    }


class FakeConn:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def rpc(self, method, params):
        self.calls.append((method, params))
        if isinstance(self.response, Exception):
            raise self.response
        return copy.deepcopy(self.response)


def observer_source():
    frames = []
    source = PythonObserverSource(frame_consumer=frames.append)
    source.observe_result("hello", {
        "protocol": PROTOCOL,
        "mc_version": "1.21.11",
        "supported_mc_versions": ["1.21.11"],
        "catalog_hash": None,
        "dimension": "minecraft:overworld",
        "origin": [200, 0, 200],
        "world_constants": {"y_sea": 62},
        "permissions": {"online": True, "offline": True, "build_range": 1000},
    }, 1)
    assert source.active
    frames.clear()
    return source, frames


def test_b9_package_version_and_unchanged_protocol():
    assert PROTOCOL == "23.2.0"
    project = (Path(__file__).parents[1] / "pyproject.toml").read_text()
    assert 'version = "2320.0.0b9"' in project


@pytest.mark.parametrize("events", [
    [event(1), event(2, "chat_posted", message="hello"), event(3)],
    [event(1, "chat_posted", message="hello"), event(2), event(3)],
    [event(1), event(2), event(3)],
])
def test_poll_omits_unknown_events_and_advances_the_server_cursor(events):
    wire_result = result(events, filtered_out=4)
    conn = FakeConn(wire_result)
    mc = Minecraft(conn)
    batch = mc.pollEvents(max_events=16)
    assert all(isinstance(item, ChatPostedEvent) for item in batch.events)
    assert [item.sequence for item in batch.events] == [
        item["sequence"] for item in events if item["type"] == "chat_posted"
    ]
    assert batch.through_sequence == 3
    assert batch.latest_sequence == 7
    assert batch.filtered_out == 4
    assert dict(batch.loss_totals) == {
        "overflow": 5, "capacity": 2, "explicitly_discarded": 1,
    }
    conn.response = result([], through=3)
    assert mc.pollEvents().events == ()
    assert conn.calls == [("events.poll", [0, {"max_events": 16}]), ("events.poll", [3])]
    assert wire_result["events"] == events
    source, frames = observer_source()
    source.observe_result("events.poll", wire_result, 2)
    observed = validate_snapshot(source.snapshot(frames))
    assert observed["streams"][0]["frames"][0]["payload"]["result"] == wire_result


def test_unknown_event_decoder_validates_common_fields_without_reading_payload():
    assert decode_event(event(1, future_payload={"anything": [1, 2]})) is None


@pytest.mark.parametrize("change", [
    {"type": None}, {"type": ""}, {"type": True}, {"type": []},
    {"sequence": True}, {"sequence": -1}, {"sequence": 1.5},
    {"dimension": "overworld"}, {"dimension": None},
    {"origin": [1, 2]}, {"origin": [1, True, 3]}, {"origin": [1, 2.5, 3]},
])
def test_unknown_event_still_rejects_invalid_common_fields(change):
    conn = FakeConn(result([{**event(1), **change}]))
    mc = Minecraft(conn)
    with pytest.raises(McRemoteError):
        mc.pollEvents()
    assert mc._event_cursor == 0
    source, frames = observer_source()
    source.observe_result("events.poll", conn.response, 2)
    assert frames == []


@pytest.mark.parametrize("events,through,latest", [
    ([event(1), event(1)], 3, 7),
    ([event(2), event(1)], 3, 7),
    ([event(0)], 3, 7),
    ([event(4)], 3, 7),
    ([event(1)], 8, 7),
    ([event(2), event(1, "chat_posted", message="hello")], 3, 7),
])
def test_omitted_events_still_count_in_order_and_cursor_validation(events, through, latest):
    response = result(events, through, latest)
    mc = Minecraft(FakeConn(response))
    with pytest.raises(McRemoteError):
        mc.pollEvents()
    assert mc._event_cursor == 0
    source, frames = observer_source()
    source.observe_result("events.poll", response, 2)
    assert frames == []


def test_response_behind_current_cursor_is_rejected_even_if_all_events_are_unknown():
    conn = FakeConn(result([event(1)]))
    mc = Minecraft(conn)
    mc.pollEvents()
    conn.response = result([event(2)], through=2)
    with pytest.raises(McRemoteError, match="cursor bounds"):
        mc.pollEvents()
    assert mc._event_cursor == 3


@pytest.mark.parametrize("known", [
    event(2, "chat_posted"),
    event(2, "chat_posted", message=123),
    event(2, "chat_posted", message="hello", extra=True),
    event(2, "pickaxe_poke"),
    event(2, "projectile_hit"),
])
def test_malformed_known_payload_rejects_whole_batch_without_cursor_change(known):
    conn = FakeConn(result([event(1), known, event(3)]))
    mc = Minecraft(conn)
    for _ in range(2):
        with pytest.raises(McRemoteError):
            mc.pollEvents()
    assert conn.calls == [("events.poll", [0]), ("events.poll", [0])]
    assert mc._event_cursor == 0
    source, frames = observer_source()
    source.observe_result("events.poll", conn.response, 2)
    assert frames == []


def test_observer_shows_unknown_common_context_and_preserves_counters():
    response = result([
        event(1, private_future_payload={"token": "do-not-observe"}),
        event(2, "chat_posted", message="hello"),
        event(3, future_payload=[1, 2]),
    ])
    source, frames = observer_source()
    source.observe_result("events.poll", response, 2)
    snapshot = validate_snapshot(source.snapshot(frames))
    observed = snapshot["streams"][0]["frames"][0]["payload"]["result"]
    assert observed == {**response, "events": [
        event(1), response["events"][1], event(3),
    ]}
    assert "private_future_payload" in response["events"][0]


def test_chat_post_null_return_and_observer_frame():
    conn = FakeConn(None)
    assert Minecraft(conn).postToChat("hello") is None
    assert conn.calls == [("chat.post", ["hello"])]
    source, frames = observer_source()
    source.observe_result("chat.post", None, 2)
    assert frames[0]["payload"] == {"result": None}
    validate_snapshot(source.snapshot(frames))


@pytest.mark.parametrize("value", ["hello", True, 0, {}, []])
def test_chat_post_rejects_non_null_success_in_client_and_observer(value):
    with pytest.raises(McRemoteError, match="must be null"):
        Minecraft(FakeConn(value)).postToChat("hello")
    source, frames = observer_source()
    source.observe_result("chat.post", value, 2)
    assert frames == []
    source.observe_result("chat.post", None, 3)
    snapshot = source.snapshot(frames)
    snapshot["streams"][0]["frames"][0]["payload"] = {"result": value}
    with pytest.raises(ObserverValidationError, match="must be null"):
        validate_snapshot(snapshot)


def test_chat_post_propagates_rpc_error_without_retry():
    failure = McRpcError(-32000, "permission denied", {"reason": "build_denied"})
    conn = FakeConn(failure)
    with pytest.raises(McRpcError) as caught:
        Minecraft(conn).postToChat("hello")
    assert caught.value is failure
    assert conn.calls == [("chat.post", ["hello"])]
