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

    Protocol:
        <4-byte native-endian payload length><UTF-8 JSON payload>

    Authentication errors (error_type == "auth_error") are returned as
    normal responses because greetd considers them a normal authentication
    failure rather than a fatal IPC error.

    A general greetd error (error_type == "error") is raised as GreetdError.

    Based on the current greetd IPC protocol:
        create_session
        post_auth_message_response
        start_session
        cancel_session
    """

    def __init__(self, sock_path: Optional[str] = None):
        self.sock_path = sock_path or os.environ.get("GREETD_SOCK")

        if not self.sock_path:
            raise ValueError(
                "GREETD_SOCK environment variable is not set. "
                "Are you running under greetd?"
            )

        self.sock: Optional[socket.socket] = None

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def connect(self) -> None:
        """Connect to the greetd Unix socket."""

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

    def close(self) -> None:
        """Close the greetd connection."""

        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    # ------------------------------------------------------------------
    # Low-level protocol
    # ------------------------------------------------------------------

    def _require_socket(self) -> socket.socket:
        if self.sock is None:
            raise ConnectionError("Not connected to greetd.")

        return self.sock

    def _send(self, data: Dict[str, Any]) -> None:
        """
        Send one greetd request.

        greetd expects:
            uint32 native-endian payload length
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

        socket.recv() is allowed to return fewer bytes than requested,
        so using a single recv(4) for the header is not safe.
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
        """Receive and decode one greetd response."""

        header = self._recv_exact(4)

        length = struct.unpack(
            "=I",
            header,
        )[0]

        payload = self._recv_exact(length)

        try:
            response = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ConnectionError(f"Invalid JSON received from greetd: {exc}") from exc

        if not isinstance(response, dict):
            raise ConnectionError("Invalid response from greetd: expected JSON object.")

        return response

    def send_request(
        self,
        req: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Send a request and receive its response.

        IMPORTANT:

        greetd's `auth_error` is deliberately NOT converted into
        GreetdError. It is a normal authentication failure and the
        caller needs to be able to handle it.

        A general greetd `error` is still raised.
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

            # auth_error means the password/authentication failed.
            #
            # This is explicitly a non-fatal error in the greetd
            # protocol and should be handled by the greeter.
            if error_type == "auth_error":
                return response

            raise GreetdError(
                error_type=error_type,
                description=description,
            )

        return response

    # ------------------------------------------------------------------
    # Protocol requests
    # ------------------------------------------------------------------

    def create_session(
        self,
        username: str,
    ) -> Dict[str, Any]:
        """
        Create a session and begin authentication.

        Returns either:
            success
            auth_message
            auth_error
        """

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
        """
        Answer the current authentication message.

        Returns either:
            success
            auth_message
            auth_error
        """

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
        """
        Start the authenticated session.

        This should only be called after authentication returned
        `success`.
        """

        req: Dict[str, Any] = {
            "type": "start_session",
            "cmd": cmd,
        }

        if env is not None:
            req["env"] = env

        return self.send_request(req)

    def cancel_session(self) -> Dict[str, Any]:
        """
        Cancel the session currently under configuration.

        IMPORTANT:
        This should only be used while the session is still active.

        greetd automatically cancels a session when an error occurs,
        including an authentication error, so callers should NOT call
        this after receiving auth_error.
        """

        return self.send_request(
            {
                "type": "cancel_session",
            }
        )

    # ------------------------------------------------------------------
    # High-level authentication helper
    # ------------------------------------------------------------------

    def authenticate(
        self,
        username: str,
        prompt_handler: Callable[[str, str], Optional[str]],
    ) -> bool:
        """
        Perform a complete authentication flow.

        prompt_handler receives:

            (message, message_type)

        where message_type is one of:

            visible
            secret
            info
            error

        Returns True on successful authentication.

        Returns False on authentication failure.

        Raises GreetdError / ConnectionError on actual IPC failures.
        """

        response = self.create_session(username)

        while response.get("type") == "auth_message":
            msg = response.get(
                "auth_message",
                "",
            )

            msg_type = response.get(
                "auth_message_type",
                "visible",
            )

            if msg_type in ("info", "error"):
                prompt_handler(
                    msg,
                    msg_type,
                )

                response = self.post_auth_message_response()

            else:
                user_input = prompt_handler(
                    msg,
                    msg_type,
                )

                response = self.post_auth_message_response(user_input)

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
