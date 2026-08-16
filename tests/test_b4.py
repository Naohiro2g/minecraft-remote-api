"""Protocol 21.0.0 b4 paired-player pose API tests."""

from mc_remote.connection import McRpcError
from mc_remote.minecraft import Minecraft


class FakeConn:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def rpc(self, method, params=None):
        self.calls.append((method, params))
        response = self.responses[method]
        if isinstance(response, Exception):
            raise response
        return response(params) if callable(response) else response

    def close(self):
        pass


def test_getpose_uses_paired_player_without_identity_param():
    result = {
        "world": "overworld",
        "pos": [1.25, 64.5, -3.75],
        "yaw": 90.0,
        "pitch": -12.5,
    }
    fake = FakeConn({"player.getPose": result})

    assert Minecraft(fake).getPose() == result
    assert fake.calls == [("player.getPose", [])]


def test_setpose_preserves_fractional_values_and_server_normalized_result():
    result = {
        "world": "the_end",
        "pos": [1.25, 2.5, 3.75],
        "yaw": 5.0,
        "pitch": 45.5,
    }
    fake = FakeConn({"player.setPose": result})

    actual = Minecraft(fake).setPose("the_end", 1.25, 2.5, 3.75, 725.0, 45.5)

    assert actual == result
    assert fake.calls == [
        ("player.setPose", ["the_end", 1.25, 2.5, 3.75, 725.0, 45.5])
    ]


def test_setpose_teleport_failure_propagates_with_stable_reason():
    failure = McRpcError(-32000, "teleport failed", {"reason": "teleport_failed"})
    mc = Minecraft(FakeConn({"player.setPose": failure}))

    try:
        mc.setPose("overworld", 0.0, 64.0, 0.0, 0.0, 0.0)
    except McRpcError as exc:
        assert exc.reason == "teleport_failed"
    else:
        raise AssertionError("expected teleport_failed to propagate")
