"""Consume the owner's 33 B9 chat/event cases without rewriting their bytes."""

from dataclasses import fields
import hashlib
import json
from pathlib import Path

import pytest

from mc_remote.block_value import BlockValue
from mc_remote.connection import McRemoteError
from mc_remote.minecraft import Minecraft, PROTOCOL
from mc_remote.observer import validate_snapshot

from test_b9 import FakeConn, observer_source


ROOT = Path(__file__).parent / "fixtures"
FIXTURE_PATH = ROOT / "chat-event-compat-v23.2.json"
SOURCE = json.loads((ROOT / "chat-event-compat-v23.2.source.json").read_text())
FIXTURE = json.loads(FIXTURE_PATH.read_text())


def event_snapshot(event):
    result = {}
    for field in fields(event):
        value = getattr(event, field.name)
        if isinstance(value, BlockValue):
            value = {"block_id": value.block_id, "state": dict(value.state)}
        elif isinstance(value, tuple):
            value = list(value)
        result[field.name] = value
    return result


def seed_status(mc, conn, previous):
    conn.response = {
        "events": [],
        "through_sequence": previous["cursor"],
        "latest_sequence": previous["latestSequence"],
        "filtered_out": 0,
        "overflow_dropped_total": previous["overflowDroppedTotal"],
        "capacity_dropped_total": previous["capacityDroppedTotal"],
        "explicitly_discarded_total": previous["explicitlyDiscardedTotal"],
    }
    mc.pollEvents()


def test_shared_fixture_identity_and_33_case_inventory():
    body = FIXTURE_PATH.read_bytes()
    assert len(body) == SOURCE["bytes"] == 32382
    assert hashlib.sha256(body).hexdigest() == SOURCE["sha256"] == (
        "670b0a86df1956c0e44c6986a0a2598caab32c7328804f9c703190e62e9dd727"
    )
    assert SOURCE["repository"] == "Naohiro2g/minecraft-remote-tooling"
    assert SOURCE["commit"] == "dc1ab834183e29f2eb03059b07e99d2b463776ee"
    assert SOURCE["path"] == "packages/protocol/test/fixtures/chat-event-compat-v23.2.json"
    assert FIXTURE["schema"] == "mcremote.chat-event-compat.v23.2"
    assert FIXTURE["protocol"] == PROTOCOL == "23.2.0"
    assert FIXTURE["knowledge_contract"] == SOURCE["knowledge_contract"]
    assert FIXTURE["knowledge_contract"]["commit"] == "900f6f4b8027d265a62ba7f139d4f3b1bbe78100"
    assert FIXTURE["knowledge_contract"]["decisions"] == ["2026-10-03-01", "2026-10-03-02"]
    ids = [case["id"] for case in (
        FIXTURE["chat_post"]["cases"] + FIXTURE["event_batches"]["cases"]
        + FIXTURE["event_batches"]["stateful_rejections"]
    )]
    assert len(ids) == len(set(ids)) == SOURCE["cases"] == 33


@pytest.mark.parametrize("case", FIXTURE["chat_post"]["cases"], ids=lambda item: item["id"])
def test_shared_chat_post_success_shape_on_client_and_observer(case):
    conn = FakeConn(case["result"])
    mc = Minecraft(conn)
    params = FIXTURE["chat_post"]["params"]
    if case["accept"]:
        assert mc.postToChat(*params) is None
    else:
        with pytest.raises(McRemoteError):
            mc.postToChat(*params)
    assert conn.calls == [(FIXTURE["chat_post"]["method"], params)]
    source, frames = observer_source()
    source.observe_result(FIXTURE["chat_post"]["method"], case["result"], 2)
    assert bool(frames) == case["accept"]
    if frames:
        assert frames[0]["payload"] == {"result": None}
        validate_snapshot(source.snapshot(frames))


@pytest.mark.parametrize("case", FIXTURE["event_batches"]["cases"], ids=lambda item: item["id"])
def test_shared_event_batches_keep_cursor_losses_and_observer_summary(case):
    conn = FakeConn(None)
    mc = Minecraft(conn)
    seed_status(mc, conn, case["previous_status"])
    previous = mc._last_event_batch
    conn.response = case["result"]
    if case["accept"]:
        batch = mc.pollEvents()
        expected = case["expected_client"]
        assert [event_snapshot(item) for item in batch.events] == expected["events"]
        assert mc._event_cursor == batch.through_sequence == expected["cursor"]
        for name in (
            "latest_sequence", "filtered_out", "overflow_dropped_total",
            "capacity_dropped_total", "explicitly_discarded_total",
        ):
            assert getattr(batch, name) == case["result"][name]
    else:
        with pytest.raises(McRemoteError):
            mc.pollEvents()
        assert mc._event_cursor == case["after_sequence"]
        assert mc._last_event_batch is previous
    assert conn.calls[-1] == (FIXTURE["event_batches"]["method"], [case["after_sequence"]])

    source, frames = observer_source()
    source.observe_result(FIXTURE["event_batches"]["method"], case["result"], 2)
    assert bool(frames) == case["accept"]
    if frames:
        observed = validate_snapshot(source.snapshot(frames))
        assert observed["streams"][0]["frames"][0]["payload"]["result"] == case["expected_observer"]


@pytest.mark.parametrize("case", FIXTURE["event_batches"]["stateful_rejections"], ids=lambda item: item["id"])
def test_shared_invalid_state_keeps_previous_cursor_and_loss_totals(case):
    conn = FakeConn(None)
    mc = Minecraft(conn)
    seed_status(mc, conn, case["previous_status"])
    previous = mc._last_event_batch
    conn.response = case["result"]
    for _ in range(2):
        with pytest.raises(McRemoteError):
            mc.pollEvents()
    assert mc._event_cursor == case["after_sequence"]
    assert mc._last_event_batch is previous
    assert conn.calls[-2:] == [("events.poll", [case["after_sequence"]])] * 2


@pytest.mark.parametrize("counter", [
    "overflow_dropped_total", "capacity_dropped_total", "explicitly_discarded_total",
])
def test_loss_totals_reset_on_a_new_epoch_and_never_on_invalid_response(counter):
    conn = FakeConn(None)
    conn.epoch = 1
    mc = Minecraft(conn)
    seed_status(mc, conn, {
        "cursor": 1, "latestSequence": 4, "overflowDroppedTotal": 2,
        "capacityDroppedTotal": 2, "explicitlyDiscardedTotal": 2,
    })
    previous = mc._last_event_batch
    conn.response = {
        "events": [], "through_sequence": 1, "latest_sequence": 4,
        "filtered_out": 0, "overflow_dropped_total": 2,
        "capacity_dropped_total": 2, "explicitly_discarded_total": 2,
        counter: 1,
    }
    with pytest.raises(McRemoteError, match="loss counter"):
        mc.pollEvents()
    assert mc._last_event_batch is previous
    conn.epoch = 2
    conn.response = FIXTURE["event_batches"]["cases"][1]["result"]
    batch = mc.pollEvents()
    assert conn.calls[-1] == ("events.poll", [0])
    assert batch.events == ()
    assert batch.through_sequence == 1
    assert dict(batch.loss_totals) == {"overflow": 0, "capacity": 0, "explicitly_discarded": 0}
