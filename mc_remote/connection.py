import socket
import select
import sys
from .util import flatten_parameters_to_bytestring


class Connection:
    """Connection to a Minecraft Pi game"""

    RequestFailed = "Fail"

    def __init__(self, address, port, debug=False):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(10)
        self.socket.connect((address, port))
        self.socket.settimeout(60)  # doc suggests None for makefile
        self.lastSent = ""
        self.debug = debug
        self.reader = self.socket.makefile("r")

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
        # return True

    def drain(self):
        """Drains the socket of incoming data"""
        while True:
            try:
                readable, _, _ = select.select([self.socket], [], [], 0.0)
                if not readable:
                    break
                data = self.socket.recv(1500)
                if self.debug:
                    e = f"Drained Data: <{data.strip()}>\n"
                    e += f"Last Message: <{self.lastSent.strip()}>\n"
                    sys.stderr.write(e)
            except socket.error as e:
                sys.stderr.write(f"Connection lost during draining: {e}\n")
                sys.exit(1)

    def send(self, f, *data):
        """
        Sends data. Note that a trailing newline '\n' is added here
        """
        if not self.is_connected():
            sys.stderr.write("Connection to the server is lost\n")
            sys.exit(1)
        s = b"".join([f, b"(", flatten_parameters_to_bytestring(data), b")", b"\n"])
        # print(s)
        self._send(s)

    def _send(self, s):
        """
        The actual socket interaction from self.send, extracted for easier mocking
        and testing
        """
        self.drain()
        self.lastSent = s

        self.socket.sendall(s)

    def receive(self):
        """Receives data. Note that the trailing newline '\n' is trimmed"""
        if not self.is_connected():
            sys.stderr.write("Connection to the server is lost\n")
            sys.exit(1)
        try:
            s = self.reader.readline().rstrip("\n")
            if s == Connection.RequestFailed:
                sys.stderr.write(f"{self.lastSent.strip()} failed\n")
                sys.exit(1)
            return s
        except socket.error as e:
            sys.stderr.write(f"Failed to receive data: {e}\n")
            sys.exit(1)

    def sendReceive(self, *data):
        """Sends and receives data"""
        self.send(*data)
        response = self.receive()
        return response
