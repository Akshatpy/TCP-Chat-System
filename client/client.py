import asyncio
import base64
import json
import os
import uuid
from typing import Dict, Optional
from server.protocol import encode_message, decode_message, MessageType, ProtocolMessage
from server.tls import create_client_ssl_context

class ChatClient:
    """
    Simple CLI client for interacting with the TCP chat server.
    """
    def __init__(self, host: str = "127.0.0.1", port: int = 8888) -> None:
        self.host = host
        self.port = port
        self.reader: asyncio.StreamReader
        self.writer: asyncio.StreamWriter
        self.username: Optional[str] = None
        self.incoming_files: Dict[str, bytearray] = {}
        self.pending_acks: Dict[str, asyncio.Future] = {}

    async def connect(self) -> None:
        ssl_context = create_client_ssl_context()
        try:
            self.reader, self.writer = await asyncio.open_connection(
                self.host,
                self.port,
                ssl=ssl_context,
                server_hostname="localhost",
            )
            print(f"Connected to {self.host}:{self.port}")
        except ConnectionRefusedError:
            print(f"Error: Could not connect to server at {self.host}:{self.port}. Is the server running?")
            os._exit(1)
        except Exception as e:
            print(f"Failed to connect: {e}")
            os._exit(1)

    async def authenticate(self) -> None:
        while True:
            action = input("Login or register? [l/r]: ").strip().lower()
            if action not in ("l", "r"):
                continue
            username = input("Username: ").strip()
            password = input("Password: ").strip()
            req_id = str(uuid.uuid4())
            payload = {
                "action": "login" if action == "l" else "register",
                "username": username,
                "password": password,
            }
            self.writer.write(encode_message(MessageType.AUTH, payload, req_id))
            await self.writer.drain()
            while True:
                line = await self.reader.readline()
                if not line:
                    raise RuntimeError("Connection closed by server")
                msg = decode_message(line)
                if msg.type == MessageType.SYSTEM.value:
                    print(f"[SYSTEM] {msg.payload.get('message')}")
                    continue
                if msg.type == MessageType.AUTH_OK.value:
                    self.username = username
                    print(f"Authenticated as {username}")
                    break
                print("Authentication failed:", msg.payload.get("error"))
                break
            if self.username:
                break

    async def _recv_loop(self) -> None:
        while True:
            line = await self.reader.readline()
            if not line:
                print("Server disconnected.")
                os._exit(0)
            try:
                msg = decode_message(line)
            except Exception as e:
                print("Failed to decode message:", e)
                continue
                
            if msg.msg_id and msg.msg_id in self.pending_acks:
                if not self.pending_acks[msg.msg_id].done():
                    self.pending_acks[msg.msg_id].set_result(msg)

            await self._handle_server_message(msg)

    async def _handle_server_message(self, msg: ProtocolMessage) -> None:
        t = msg.type
        if t == MessageType.MSG.value:
            print(f"[{msg.payload['room']}:{msg.payload['sequence_number']}] {msg.payload['sender']}: {msg.payload['content']}")
        elif t == MessageType.PMSG.value:
            print(f"[PM] {msg.payload['sender']} -> {msg.payload.get('receiver')}: {msg.payload['content']}")
        elif t == MessageType.FILE_END.value:
            print(f"[FILE] {json.dumps(msg.payload)}")
            # Handle client download completion
            file_id = msg.payload.get("file_id")
            filename = msg.payload.get("filename")
            if file_id in self.incoming_files and filename:
                os.makedirs("client_downloads", exist_ok=True)
                path = os.path.join("client_downloads", f"{file_id}_{os.path.basename(filename)}")
                with open(path, "wb") as f:
                    f.write(self.incoming_files[file_id])
                print(f"File downloaded successfully to {path}")
                del self.incoming_files[file_id]
        elif t == MessageType.FILE_CHUNK.value:
            file_id = msg.payload.get("file_id")
            data_b64 = msg.payload.get("data_b64")
            if file_id and data_b64:
                data = base64.b64decode(data_b64)
                if file_id not in self.incoming_files:
                    self.incoming_files[file_id] = bytearray()
                self.incoming_files[file_id].extend(data)
        elif t == MessageType.SYSTEM.value:
            print(f"[SYSTEM] {msg.payload.get('message')}")
        elif t == MessageType.ERROR.value:
            print(f"[ERROR] {msg.payload.get('error')}")
        elif t == MessageType.LIST_ROOMS.value:
            print("Rooms:", msg.payload.get("rooms"))
        elif t == MessageType.LIST_USERS.value:
            print("Active users:", msg.payload.get("users"))

    async def _send_file(self, target: str, is_room: bool, path: str) -> None:
        if not os.path.isfile(path):
            print("File does not exist")
            return
        size = os.path.getsize(path)
        req_id = str(uuid.uuid4())
        meta = {
            "target": target,
            "is_room": is_room,
            "filename": os.path.basename(path),
            "size": size,
        }
        fut = asyncio.get_running_loop().create_future()
        self.pending_acks[req_id] = fut
        
        self.writer.write(encode_message(MessageType.FILE_SEND, meta, req_id))
        await self.writer.drain()
        # Wait for ACK with file_id
        try:
            msg = await asyncio.wait_for(fut, timeout=10.0)
        except asyncio.TimeoutError:
            print("Timeout waiting for server ACK.")
            return
            
        if msg.type != MessageType.ACK.value or msg.payload.get("action") != "FILE_SEND":
            print("Failed to initiate file transfer")
            return
        file_id = msg.payload["file_id"]
        print(f"Sending file with id {file_id}...")
        with open(path, "rb") as f:
            while True:
                chunk = f.read(4096)
                if not chunk:
                    break
                data_b64 = base64.b64encode(chunk).decode("ascii")
                self.writer.write(
                    encode_message(
                        MessageType.FILE_CHUNK,
                        {"file_id": file_id, "data_b64": data_b64},
                        str(uuid.uuid4()),
                    )
                )
                await self.writer.drain()
        # send end marker
        self.writer.write(
            encode_message(
                MessageType.FILE_END,
                {"file_id": file_id},
                str(uuid.uuid4()),
            )
        )
        await self.writer.drain()
        print("File transfer completed (client-side).")

    async def _user_input_loop(self) -> None:
        help_text = (
            "Commands:\n"
            "  /join <room>\n"
            "  /leave <room>\n"
            "  /rooms\n"
            "  /users\n"
            "  /msg <room> <text>\n"
            "  /pmsg <user> <text>\n"
            "  /sendfile_room <room> <path>\n"
            "  /sendfile_user <user> <path>\n"
            "  /quit\n"
        )
        print(help_text)
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, input, "> ")
            line = line.strip()
            if not line:
                continue
            if line == "/quit":
                print("Bye.")
                os._exit(0)
            if line.startswith("/join "):
                room = line.split(maxsplit=1)[1]
                self.writer.write(
                    encode_message(
                        MessageType.JOIN,
                        {"room": room},
                        str(uuid.uuid4()),
                    )
                )
                await self.writer.drain()
            elif line.startswith("/leave "):
                room = line.split(maxsplit=1)[1]
                self.writer.write(
                    encode_message(
                        MessageType.LEAVE,
                        {"room": room},
                        str(uuid.uuid4()),
                    )
                )
                await self.writer.drain()
            elif line == "/rooms":
                self.writer.write(
                    encode_message(
                        MessageType.LIST_ROOMS,
                        {},
                        str(uuid.uuid4()),
                    )
                )
                await self.writer.drain()
            elif line == "/users":
                self.writer.write(
                    encode_message(
                        MessageType.LIST_USERS,
                        {},
                        str(uuid.uuid4()),
                    )
                )
                await self.writer.drain()
            elif line.startswith("/msg "):
                try:
                    _, room, text = line.split(maxsplit=2)
                except ValueError:
                    print("Usage: /msg <room> <text>")
                    continue
                self.writer.write(
                    encode_message(
                        MessageType.MSG,
                        {"room": room, "content": text},
                        str(uuid.uuid4()),
                    )
                )
                await self.writer.drain()
            elif line.startswith("/pmsg "):
                try:
                    _, user, text = line.split(maxsplit=2)
                except ValueError:
                    print("Usage: /pmsg <user> <text>")
                    continue
                self.writer.write(
                    encode_message(
                        MessageType.PMSG,
                        {"to": user, "content": text},
                        str(uuid.uuid4()),
                    )
                )
                await self.writer.drain()
            elif line.startswith("/sendfile_room "):
                try:
                    _, room, path = line.split(maxsplit=2)
                except ValueError:
                    print("Usage: /sendfile_room <room> <path>")
                    continue
                await self._send_file(room, True, path)
            elif line.startswith("/sendfile_user "):
                try:
                    _, user, path = line.split(maxsplit=2)
                except ValueError:
                    print("Usage: /sendfile_user <user> <path>")
                    continue
                await self._send_file(user, False, path)
            else:
                print(help_text)

    async def run(self) -> None:
        await self.connect()
        await self.authenticate()
        await asyncio.gather(self._recv_loop(), self._user_input_loop())


if __name__ == "__main__":
    try:
        asyncio.run(ChatClient().run())
    except KeyboardInterrupt:
        print("Exiting client...")


