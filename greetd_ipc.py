import os
import json
import struct
import socket
from typing import List, Dict, Any, Callable, Optional

class GreetdError(Exception):
    """Raised when greetd returns an error response."""
    def __init__(self, error_type: str, description: str):
        super().__init__(f"{error_type}: {description}")
        self.error_type = error_type
        self.description = description

class GreetdClient:
    def __init__(self, sock_path: Optional[str] = None):
        """
        Initializes the client. Uses the GREETD_SOCK environment variable
        by default, which greetd automatically sets.
        """
        self.sock_path = sock_path or os.environ.get("GREETD_SOCK")
        if not self.sock_path:
            raise ValueError("GREETD_SOCK environment variable is not set. Are you running under greetd?")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def connect(self):
        self.sock.connect(self.sock_path)

    def close(self):
        self.sock.close()

    # ==========================================
    # ADVANCED: Low-Level Protocol & Base Functions
    # ==========================================

    def _send(self, data: Dict[str, Any]):
        """Packs a JSON payload with a 4-byte length header (native byte order)."""
        payload = json.dumps(data).encode("utf-8")
        header = struct.pack("=I", len(payload))
        self.sock.sendall(header + payload)

    def _recv(self) -> Dict[str, Any]:
        """Unpacks the 4-byte length header and reads the exact JSON payload length."""
        header = self.sock.recv(4)
        if not header or len(header) < 4:
            raise ConnectionError("Failed to read length header from greetd.")
        
        length = struct.unpack("=I", header)[0]
        data = b""
        
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk:
                raise ConnectionError("Connection closed while reading payload from greetd.")
            data += chunk
            
        return json.loads(data.decode("utf-8"))

    def send_request(self, req: Dict[str, Any]) -> Dict[str, Any]:
        """Sends a request and checks for protocol-level errors."""
        self._send(req)
        response = self._recv()
        
        if response.get("type") == "error":
            raise GreetdError(
                error_type=response.get("error_type", "unknown_error"),
                description=response.get("description", "No description provided.")
            )
        return response

    # ==========================================
    # ADVANCED: 1-to-1 Protocol Mappings
    # ==========================================

    def create_session(self, username: str) -> Dict[str, Any]:
        """Starts a session initialization for a given username."""
        return self.send_request({
            "type": "create_session",
            "username": username
        })

    def post_auth_message_response(self, response: Optional[str] = None) -> Dict[str, Any]:
        """Replies to an auth_message (like providing a password)."""
        return self.send_request({
            "type": "post_auth_message_response",
            "response": response
        })

    def start_session(self, cmd: List[str], env: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Spawns the user session and exits.
        Must only be called after authentication returns 'success'.
        """
        req = {"type": "start_session", "cmd": cmd}
        if env:
            req["env"] = env
        return self.send_request(req)

    def cancel_session(self) -> Dict[str, Any]:
        """Cancels an ongoing authentication process."""
        return self.send_request({"type": "cancel_session"})


    # ==========================================
    # EASY: High-Level Abstractions
    # ==========================================

    def authenticate(self, username: str, prompt_handler: Callable[[str, str], Optional[str]]) -> bool:
        """
        Handles the entire PAM authentication loop automatically.
        
        :param username: The username to log in as.
        :param prompt_handler: A callback function that takes (message, message_type)
                               and returns a string (the user's input) or None.
                               message_types: "visible", "secret", "info", "error".
        :return: True if authentication succeeded.
        """
        try:
            response = self.create_session(username)
            
            while response.get("type") == "auth_message":
                msg = response.get("auth_message", "")
                msg_type = response.get("auth_message_type", "visible")
                
                # "info" and "error" messages don't require user input, just an acknowledgment.
                if msg_type in ("info", "error"):
                    prompt_handler(msg, msg_type)
                    response = self.post_auth_message_response(None)
                else:
                    # "visible" (e.g. username prompt) or "secret" (e.g. password prompt)
                    user_input = prompt_handler(msg, msg_type)
                    response = self.post_auth_message_response(user_input)
                    
            return response.get("type") == "success"
            
        except GreetdError:
            return False
