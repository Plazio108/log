#!/usr/bin/env python3
"""
Mock greetd IPC Socket Server
Used for testing greetd Python TUI greeters locally inside Hyprland.
"""

import os
import sys
import json
import socket
import struct
import argparse
import subprocess
from typing import Dict, Any, Optional

DEFAULT_SOCKET_PATH = "/tmp/mock_greetd.sock"
MOCK_PASSWORD = "1234"  # Default accepted password for testing


class MockGreetdServer:
    def __init__(self, socket_path: str = DEFAULT_SOCKET_PATH, mock_password: str = MOCK_PASSWORD):
        self.socket_path = socket_path
        self.mock_password = mock_password
        self.server_sock: Optional[socket.socket] = None
        self.current_user: Optional[str] = None
        self.authenticated = False

    def log(self, prefix: str, msg: str):
        print(f"\033[1;34m[MOCK SERVER]\033[0m \033[1m{prefix}:\033[0m {msg}")

    def error_log(self, msg: str):
        print(f"\033[1;31m[MOCK SERVER ERROR]\033[0m {msg}")

    def setup_socket(self):
        # Remove old socket file if it exists
        if os.path.exists(self.socket_path):
            os.remove(self.socket_path)

        self.server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.server_sock.bind(self.socket_path)
        self.server_sock.listen(1)
        self.log("INIT", f"Listening on Unix socket: {self.socket_path}")

    def send_message(self, client_sock: socket.socket, data: Dict[str, Any]):
        payload = json.dumps(data).encode("utf-8")
        header = struct.pack("=I", len(payload))
        client_sock.sendall(header + payload)
        self.log("SENT", json.dumps(data))

    def recv_message(self, client_sock: socket.socket) -> Optional[Dict[str, Any]]:
        header = client_sock.recv(4)
        if not header or len(header) < 4:
            return None
        length = struct.unpack("=I", header)[0]

        data = b""
        while len(data) < length:
            chunk = client_sock.recv(length - len(data))
            if not chunk:
                return None
            data += chunk

        msg = json.loads(data.decode("utf-8"))
        self.log("RECV", json.dumps(msg))
        return msg

    def handle_client(self, client_sock: socket.socket):
        self.log("CLIENT", "TUI client connected.")
        self.authenticated = False
        self.current_user = None

        try:
            while True:
                msg = self.recv_message(client_sock)
                if not msg:
                    self.log("CLIENT", "Client disconnected.")
                    break

                req_type = msg.get("type")

                # 1. Handle create_session
                if req_type == "create_session":
                    self.current_user = msg.get("username", "unknown")
                    self.log("AUTH", f"Session request for user: '{self.current_user}'")
                    # Send PAM secret/password prompt back to TUI
                    self.send_message(client_sock, {
                        "type": "auth_message",
                        "auth_message_type": "secret",
                        "auth_message": f"Password for {self.current_user}: "
                    })

                # 2. Handle post_auth_message_response (Password check)
                elif req_type == "post_auth_message_response":
                    user_resp = msg.get("response", "")
                    if user_resp == self.mock_password:
                        self.authenticated = True
                        self.log("AUTH", "\033[1;32mAuthentication SUCCESSFUL!\033[0m")
                        self.send_message(client_sock, {"type": "success"})
                    else:
                        self.authenticated = False
                        self.log("AUTH", "\033[1;31mAuthentication FAILED!\033[0m")
                        self.send_message(client_sock, {
                            "type": "error",
                            "error_type": "auth_error",
                            "description": f"Invalid password. (Mock password is '{self.mock_password}')"
                        })

                # 3. Handle start_session
                elif req_type == "start_session":
                    if not self.authenticated:
                        self.send_message(client_sock, {
                            "type": "error",
                            "error_type": "auth_error",
                            "description": "Cannot start session without authentication."
                        })
                        continue

                    cmd = msg.get("cmd", [])
                    env = msg.get("env", [])
                    self.log("LAUNCH", f"\033[1;32mSpawning session command:\033[0m {cmd}")
                    self.log("LAUNCH", f"Environment variables: {env}")

                    # Acknowledge success to the TUI before client exits
                    self.send_message(client_sock, {"type": "success"})
                    self.log("SYSTEM", "Mock login flow complete. Resetting session state.")

                # 4. Handle cancel_session
                elif req_type == "cancel_session":
                    self.authenticated = False
                    self.current_user = None
                    self.log("AUTH", "Session cancelled by client.")
                    self.send_message(client_sock, {"type": "success"})

                else:
                    self.send_message(client_sock, {
                        "type": "error",
                        "error_type": "unknown_request",
                        "description": f"Unknown request type: {req_type}"
                    })

        except ConnectionResetError:
            self.error_log("Client abruptly closed connection.")
        finally:
            client_sock.close()

    def run(self):
        self.setup_socket()
        try:
            while True:
                client_sock, _ = self.server_sock.accept()
                self.handle_client(client_sock)
        except KeyboardInterrupt:
            self.log("SYSTEM", "Server shutting down.")
        finally:
            if self.server_sock:
                self.server_sock.close()
            if os.path.exists(self.socket_path):
                os.remove(self.socket_path)


def main():
    parser = argparse.ArgumentParser(description="Mock greetd IPC Server")
    parser.add_argument("--socket", default=DEFAULT_SOCKET_PATH, help="Unix socket path")
    parser.add_argument("--password", default=MOCK_PASSWORD, help="Mock password to accept")
    parser.add_argument("--exec", help="Optional TUI script/command to execute with GREETD_SOCK set")
    args = parser.parse_args()

    server = MockGreetdServer(socket_path=args.socket, mock_password=args.password)

    if args.exec:
        import threading
        # Run server in a background thread and spawn the client
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()

        env = os.environ.copy()
        env["GREETD_SOCK"] = args.socket
        
        print(f"\033[1;33m[LAUNCHER]\033[0m Spawning TUI command with GREETD_SOCK={args.socket}")
        try:
            subprocess.run(args.exec, shell=True, env=env)
        except KeyboardInterrupt:
            pass
    else:
        print(f"\nExport this in your terminal before running your TUI script:\n")
        print(f"  \033[1;32mexport GREETD_SOCK=\"{args.socket}\"\033[0m\n")
        print(f"Mock Password accepted by server: \033[1;33m{args.password}\033[0m\n")
        server.run()


if __name__ == "__main__":
    main()
