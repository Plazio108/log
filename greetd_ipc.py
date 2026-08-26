import os
import json
import struct
import socket
from typing import List, Dict, Any, Callable, Optional


class GreetdError(Exception):
    """Raised when greetd reports a fatal IPC/protocol error."""

    def __init__(self, error_type: str, description: str):
        super().__init__(f"{error_type}: {description}")
        self.error_type = error_type
        self.description = description


class GreetdClient:
    """
    Client for the greetd IPC protocol.

    A single connection is kept open for the lifetime of the greeter,
    just like nwg-hello.

    auth_error is returned as a normal response because it represents
    failed authentication, not a fatal IPC error.
    """

    def __init__(self, sock_path: Optional[str] = None):
        self.sock_path = sock_path or os.environ.get("GREETD_SOCK")

        if not self.sock_path:
            raise ValueError(
                "GREETD_SOCK environment variable is not set. "
                "Are you running under greetd?"
            )

        self.sock: Optional[socket.socket] = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    # ================================================================
    # Connection
    # ================================================================

    def connect(self):
        if self.sock is not None:
            return

        sock = socket.socket(
            socket.AF_UNIX,
            socket.SOCK_STREAM,
        )

        try:
            sock.connect(self.sock_path)
        except Exception:
            sock.close()
            raise

        self.sock = sock

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    # ================================================================
    # Low-level protocol
    # ================================================================

    def _require_socket(self) -> socket.socket:
        if self.sock is None:
            raise ConnectionError("Not connected to greetd.")

        return self.sock

    def _send(self, data: Dict[str, Any]):
        """
        Send one greetd IPC request.

        Protocol:
            4-byte native-endian payload length
            UTF-8 JSON payload
        """

        sock = self._require_socket()

        payload = json.dumps(
            data,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

        header = struct.pack(
            "=I",
            len(payload),
        )

        sock.sendall(header + payload)

    def _recv_exact(self, size: int) -> bytes:
        """
        Receive exactly `size` bytes.

        AF_UNIX SOCK_STREAM is still a stream, so recv() is not
        guaranteed to return the complete requested amount.
        """

        sock = self._require_socket()

        data = bytearray()

        while len(data) < size:
            chunk = sock.recv(size - len(data))

            if not chunk:
                raise ConnectionError("Connection closed by greetd.")

            data.extend(chunk)

        return bytes(data)

    def _recv(self) -> Dict[str, Any]:
        header = self._recv_exact(4)

        length = struct.unpack(
            "=I",
            header,
        )[0]

        payload = self._recv_exact(length)

        try:
            response = json.loads(payload.decode("utf-8"))
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ConnectionError(f"Invalid JSON received from greetd: {exc}") from exc

        if not isinstance(response, dict):
            raise ConnectionError("Invalid greetd response: expected JSON object.")

        return response

    def send_request(
        self,
        req: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Send a request and return its response.

        IMPORTANT:
        auth_error is deliberately returned instead of raised.
        """

        self._send(req)

        response = self._recv()

        if response.get("type") == "error":
            error_type = response.get(
                "error_type",
                "unknown_error",
            )

            description = response.get(
                "description",
                "No description provided.",
            )

            # Authentication failure is part of the normal
            # authentication flow.
            if error_type == "auth_error":
                return response

            raise GreetdError(
                error_type,
                description,
            )

        return response

    # ================================================================
    # greetd requests
    # ================================================================

    def create_session(
        self,
        username: str,
    ) -> Dict[str, Any]:
        return self.send_request(
            {
                "type": "create_session",
                "username": username,
            }
        )

    def post_auth_message_response(
        self,
        response: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.send_request(
            {
                "type": "post_auth_message_response",
                "response": response,
            }
        )

    def start_session(
        self,
        cmd: List[str],
        env: Optional[List[str]] = None,
    ) -> Dict[str, Any]:

        request: Dict[str, Any] = {
            "type": "start_session",
            "cmd": cmd,
        }

        if env is not None:
            request["env"] = env

        return self.send_request(request)

    def cancel_session(self) -> Dict[str, Any]:
        return self.send_request(
            {
                "type": "cancel_session",
            }
        )

    # ================================================================
    # High-level authentication
    # ================================================================

    def authenticate(
        self,
        username: str,
        prompt_handler: Callable[
            [str, str],
            Optional[str],
        ],
    ) -> bool:

        # Important: cancel any previous/stale session first.
        #
        # This is what nwg-hello does before create_session().
        try:
            self.cancel_session()
        except Exception:
            # There may simply be no session to cancel.
            pass

        response = self.create_session(username)

        while response.get("type") == "auth_message":
            message = response.get(
                "auth_message",
                "",
            )

            message_type = response.get(
                "auth_message_type",
                "visible",
            )

            if message_type in ("info", "error"):
                answer = None
            else:
                answer = prompt_handler(
                    message,
                    message_type,
                )

            response = self.post_auth_message_response(answer)

        if (
            response.get("type") == "error"
            and response.get("error_type") == "auth_error"
        ):
            return False

        if response.get("type") == "success":
            return True

        raise GreetdError(
            response.get(
                "error_type",
                "unknown_error",
            ),
            response.get(
                "description",
                "Unexpected greetd response.",
            ),
        )
