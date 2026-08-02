import socket
import select
import sys
import json


class McRemoteError(Exception):
    """Base class for mc_remote client errors."""


class ConnectionLostError(McRemoteError):
    """Raised when the connection to the server is lost.

    Replaces the old ``sys.exit(1)`` so that one failed stream does not take
    down the whole process (build state is scoped per stream)."""


class RequestFailedError(McRemoteError):
    """Kept for backward compatibility. Server failures are now reported as
    :class:`McRpcError` (JSON-RPC error object)."""


class McRpcError(RequestFailedError):
    """A JSON-RPC error object returned by the server.

    The machine-readable discriminator is ``reason`` (carried in
    ``error.data.reason``); ``code`` follows the JSON-RPC numbering
    (block_state_ref validation = -32602, world-state = -32000 band).
    UI / AI / tests should branch on ``reason``, not ``code``."""

    def __init__(self, code, message, data=None):
        self.code = code
        self.data = data or {}
        self.reason = self.data.get("reason")
        super().__init__(self._format(message))

    def _format(self, message):
        head = self.reason if self.reason is not None else self.code
        parts = [f"[{head}]"]
        if message:
            parts.append(str(message))
        for key in ("ref", "pos", "property", "value", "allowed"):
            if key in self.data:
                parts.append(f"{key}={self.data[key]!r}")
        return " ".join(parts)


class Connection:
    """JSON-RPC 2.0 connection to a Minecraft server (protocol 21.x).

    One instance == one stream == one build state. The wire is line-delimited
    JSON-RPC: one JSON object per line in each direction. All calls are
    synchronous request/response with id correlation."""

    def __init__(self, address, port, debug=False):
        self.address = address
        self.port = port
        self.debug = debug
        self.lastSent = b""
        self._connect()

    def _connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(10)
        self.socket.connect((self.address, self.port))
        self.socket.settimeout(60)  # doc suggests None for makefile
        self.reader = self.socket.makefile("r")
        self._id = 0

    def reconnect(self):
        """Open a fresh stream to the same server, resetting the id counter.

        Needed by the b2 auth flow: the server drops the TCP stream after
        rejecting an unauthenticated hello with ``auth_required``, and ``hello``
        is once per connection -- so the client reconnects before pairing and
        again for the authenticated hello."""
        try:
            self.reader.close()
        except Exception:
            pass
        try:
            self.socket.close()
        except Exception:
            pass
        self._connect()

    def close(self):
        """Closes the socket and associated resources"""
        if self.debug:
            sys.stderr.write("Closing connection... ")
        try:
            self.reader.close()
        except Exception as e:
            sys.stderr.write(f"Failed to close reader: {e}\n")
        try:
            self.socket.close()
        except Exception as e:
            sys.stderr.write(f"Failed to close socket: {e}\n")
        finally:
            if self.debug:
                sys.stderr.write("Connection closed\n")

    def is_connected(self):
        """Checks if the connection to the server is still active"""
        try:
            readable, _, _ = select.select([self.socket], [], [], 0)
            if readable:
                data = self.socket.recv(1, socket.MSG_PEEK)
                if not data:
                    return False
            return True
        except socket.error:
            return False

    def rpc(self, method, params=None):
        """Send a JSON-RPC request and return its ``result``.

        Raises :class:`McRpcError` if the server returns an error object, or
        :class:`ConnectionLostError` if the stream drops."""
        if not self.is_connected():
            raise ConnectionLostError("Connection to the server is lost")
        self._id += 1
        req_id = self._id
        payload = self._build_request(method, params, req_id)
        if self.debug:
            sys.stderr.write(f"-> {payload!r}\n")
        self.lastSent = payload
        try:
            self.socket.sendall(payload)
            line = self.reader.readline()
        except socket.error as e:
            raise ConnectionLostError(f"Failed to talk to the server: {e}") from e
        if line == "":
            raise ConnectionLostError("Connection closed by server")
        if self.debug:
            sys.stderr.write(f"<- {line!r}")
        return self._parse_response(line.rstrip("\n"), req_id)

    @staticmethod
    def _build_request(method, params, req_id):
        request = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            request["params"] = params
        return (json.dumps(request, separators=(",", ":")) + "\n").encode("utf8")

    @staticmethod
    def _parse_response(line, expected_id):
        try:
            msg = json.loads(line)
        except (ValueError, TypeError) as e:
            raise McRemoteError(f"Invalid JSON-RPC response: {line!r}") from e
        # Surface errors even when id is null (JSON-RPC allows a null id for
        # some server-side failures).
        if "error" in msg:
            err = msg.get("error") or {}
            raise McRpcError(err.get("code"), err.get("message"), err.get("data"))
        if msg.get("id") != expected_id:
            raise McRemoteError(
                f"JSON-RPC id mismatch: expected {expected_id}, got {msg.get('id')}"
            )
        return msg.get("result")
