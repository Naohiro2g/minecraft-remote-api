"""In-process HTTP adapter for the browser-loopback WireScope profile."""

from __future__ import annotations

import http.server
import threading

from . import _wirescope_station_contract as contract
from ._wirescope_session import encode_end, encode_snapshot


class _StationHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class LoopbackHTTPStation:
    """One-target, one-browser same-origin station bound to IPv4 loopback."""

    def __init__(self, *, app, pipeline, policy_factory):
        self.app = app
        self.pipeline = pipeline
        self._closed = threading.Event()
        handler = self._handler_type()
        self._server = _StationHTTPServer(("127.0.0.1", 0), handler)
        host, port = self._server.server_address[:2]
        if host != "127.0.0.1":
            self._server.server_close()
            raise RuntimeError("WireScope station did not bind exact IPv4 loopback")
        self.policy = policy_factory(port)
        self._server.station = self
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="mcremote-wirescope-http",
            daemon=True,
        )
        self._thread.start()

    @property
    def url(self):
        return self.policy.origin + "/"

    @property
    def port(self):
        return self._server.server_address[1]

    def close(self):
        if self._closed.is_set():
            return
        self._closed.set()
        self.pipeline.close()
        self._server.shutdown()
        self._server.server_close()
        if self._thread.is_alive() and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)

    @classmethod
    def _handler_type(cls):
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            @property
            def station(self):
                return self.server.station

            def log_message(self, _format, *_args):
                return

            def do_GET(self):
                if self.path == contract.STATION_BOOTSTRAP_PATH:
                    self._bootstrap()
                    return
                self._asset()

            def do_POST(self):
                if self.path == contract.STATION_ATTACH_PATH:
                    self._attach()
                    return
                self._json_error("invalid-request", status=404)

            def do_HEAD(self):
                self._json_error("invalid-request", status=405)

            def _single_header(self, name, *, required=False):
                values = self.headers.get_all(name, failobj=[])
                if len(values) > 1 or (required and len(values) != 1):
                    raise ValueError(f"invalid {name} header")
                return values[0] if values else None

            def _validate_asset_authority(self):
                host = self._single_header("Host", required=True)
                self.station.policy.validate_bootstrap(host=host)

            def _bootstrap(self):
                try:
                    host = self._single_header("Host", required=True)
                    origin = self._single_header("Origin")
                    self.station.policy.validate_bootstrap(
                        host=host,
                        origin=origin,
                    )
                except ValueError:
                    self._json_error("invalid-request")
                    return
                body = contract.encode_bootstrap(
                    manifest_sha256=self.station.app.manifest_sha256,
                    station_ready=self.station.pipeline.station_ready,
                )
                self._response(
                    200,
                    contract.STATION_JSON_CONTENT_TYPE,
                    body,
                )

            def _asset(self):
                try:
                    self._validate_asset_authority()
                except ValueError:
                    self._json_error("invalid-request")
                    return
                asset = self.station.app.get(self.path)
                if asset is None:
                    self._json_error("invalid-request", status=404)
                    return
                self._response(200, asset.content_type, asset.body)

            def _attach(self):
                try:
                    if self._single_header("Transfer-Encoding") is not None:
                        raise ValueError("transfer encoding is not accepted")
                    length_value = self._single_header(
                        "Content-Length",
                        required=True,
                    )
                    if not length_value.isascii() or not length_value.isdecimal():
                        raise ValueError("invalid content length")
                    content_length = int(length_value)
                    self.station.policy.validate_attach(
                        host=self._single_header("Host", required=True),
                        origin=self._single_header("Origin", required=True),
                        content_type=self._single_header(
                            "Content-Type",
                            required=True,
                        ),
                        content_length=content_length,
                    )
                    payload = self.rfile.read(content_length)
                    if len(payload) != content_length:
                        raise ValueError("truncated request body")
                    submitted = contract.parse_attach_request(payload)
                except ValueError:
                    self._json_error("invalid-request")
                    return

                result = self.station.pipeline.attach(submitted)
                if result != "redeemed":
                    self._json_error(result)
                    return
                self._stream()

            def _stream(self):
                self.send_response(200)
                self.send_header("Content-Type", contract.STATION_NDJSON_CONTENT_TYPE)
                self.send_header("Connection", "close")
                self._security_headers()
                self.end_headers()
                self.close_connection = True
                outbound = self.station.pipeline.new_outbound_queue()
                sent_terminal = False
                try:
                    while not sent_terminal:
                        snapshot, terminal = self.station.pipeline.wait_output(1)
                        if snapshot is not None:
                            value, history = snapshot
                            line = encode_snapshot(
                                value,
                                dropped_frames=history["dropped_frames"],
                            )
                            contract.validate_ndjson_line(line)
                            if not outbound.replace_snapshot(line):
                                self.station.pipeline.end_backpressure()
                        if terminal is not None:
                            line = encode_end(terminal)
                            contract.validate_ndjson_line(line)
                            outbound.append_end(line)
                        while True:
                            item = outbound.pop()
                            if item is None:
                                break
                            kind, line = item
                            self.wfile.write(line)
                            self.wfile.flush()
                            if kind == "end":
                                sent_terminal = True
                except (BrokenPipeError, ConnectionError, OSError):
                    return

            def _json_error(self, code, *, status=None):
                error = contract.attach_error(code)
                body = contract.encode_attach_error(code)
                self.close_connection = True
                self._response(
                    error.status if status is None else status,
                    contract.STATION_JSON_CONTENT_TYPE,
                    body,
                    close=True,
                )

            def _response(self, status, content_type, body, *, close=False):
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                if close:
                    self.send_header("Connection", "close")
                self._security_headers()
                self.end_headers()
                if self.command != "HEAD":
                    self.wfile.write(body)

            def _security_headers(self):
                for name, value in contract.STATION_REQUIRED_RESPONSE_HEADERS.items():
                    self.send_header(name, value)

        return Handler
