import asyncio
import time
from typing import Dict, Optional, Callable, Awaitable

from .protocol import MessageType, encode_message, decode_message, ProtocolMessage
from .room_manager import RoomManager
from .db import Database
from .file_transfer import FileTransferManager


class ClientSession:
    """
    Represents a connected client (TCP stream) and its authenticated user.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        db: Database,
        rooms: RoomManager,
        files: FileTransferManager,
        active_clients: Dict[str, "ClientSession"],
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.db = db
        self.rooms = rooms
        self.files = files
        self.active_clients = active_clients

        self.username: Optional[str] = None
        self._closed = False

    @property
    def peername(self) -> str:
        peer = self.writer.get_extra_info("peername")
        return str(peer)

    async def send(self, msg_type: MessageType, payload: Dict, msg_id: Optional[str] = None) -> None:
        if self._closed:
            return
        data = encode_message(msg_type, payload, msg_id)
        self.writer.write(data)
        await self.writer.drain()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except Exception:
            pass
        if self.username:
            # Mark user offline and clean up memberships
            self.db.set_user_active(self.username, False)
            await self.rooms.remove_user_from_all_rooms(self.username)
            current = self.active_clients.get(self.username)
            if current is self:
                self.active_clients.pop(self.username, None)

    async def handle(self) -> None:
        """
        Main loop: read JSON lines and dispatch by type.
        """
        try:
            await self.send(MessageType.SYSTEM, {"message": "Welcome. Please authenticate."})
            while not self._closed:
                line = await self.reader.readline()
                if not line:
                    break
                try:
                    proto_msg = decode_message(line)
                except Exception:
                    await self.send(MessageType.ERROR, {"error": "Malformed message"})
                    continue

                handler_name = f"_on_{proto_msg.type.lower()}"
                handler: Optional[Callable[[ProtocolMessage], Awaitable[None]]] = getattr(
                    self, handler_name, None
                )
                if not handler:
                    await self.send(MessageType.ERROR, {"error": f"Unknown type {proto_msg.type}"})
                    continue
                await handler(proto_msg)
        finally:
            await self.close()

    # === Handlers ===

    async def _on_auth(self, msg: ProtocolMessage) -> None:
        """
        AUTH payload:
        {
          "action": "login" | "register",
          "username": "...",
          "password": "..."
        }
        """
        action = msg.payload.get("action")
        username = msg.payload.get("username")
        password = msg.payload.get("password")
        if not isinstance(username, str) or not isinstance(password, str):
            await self.send(MessageType.AUTH_FAIL, {"error": "Invalid credentials"}, msg.msg_id)
            return

        if action == "register":
            created = self.db.create_user(username, password)
            if not created:
                await self.send(MessageType.AUTH_FAIL, {"error": "User exists"}, msg.msg_id)
                return

        ok = self.db.verify_user(username, password)
        if not ok:
            await self.send(MessageType.AUTH_FAIL, {"error": "Bad username/password"}, msg.msg_id)
            return

        existing = self.active_clients.get(username)
        if existing and existing is not self and not existing._closed:
            await self.send(MessageType.AUTH_FAIL, {"error": "User already logged in"}, msg.msg_id)
            return

        self.username = username
        self.db.set_user_active(username, True)
        self.active_clients[username] = self
        await self.send(MessageType.AUTH_OK, {"username": username}, msg.msg_id)

    async def _on_join(self, msg: ProtocolMessage) -> None:
        """
        JOIN payload: { "room": "room_name" }
        """
        if not self.username:
            await self.send(MessageType.ERROR, {"error": "Authenticate first"})
            return
        room = msg.payload.get("room")
        if not isinstance(room, str):
            await self.send(MessageType.ERROR, {"error": "Invalid room"})
            return
        await self.rooms.join_room(room, self.username)
        await self.send(MessageType.ACK, {"action": "JOIN", "room": room}, msg.msg_id)

    async def _on_leave(self, msg: ProtocolMessage) -> None:
        """
        LEAVE payload: { "room": "room_name" }
        """
        if not self.username:
            await self.send(MessageType.ERROR, {"error": "Authenticate first"})
            return
        room = msg.payload.get("room")
        if not isinstance(room, str):
            await self.send(MessageType.ERROR, {"error": "Invalid room"})
            return
        await self.rooms.leave_room(room, self.username)
        await self.send(MessageType.ACK, {"action": "LEAVE", "room": room}, msg.msg_id)

    async def _on_kick(self, msg: ProtocolMessage) -> None:
        if self.username != "admin":
            await self.send(MessageType.ERROR, {"error": "Unauthorized"})
            return
        room = msg.payload.get("room")
        user = msg.payload.get("user")
        if not isinstance(room, str) or not isinstance(user, str):
            await self.send(MessageType.ERROR, {"error": "Invalid kick parameters"})
            return
        await self.rooms.leave_room(room, user)
        target = self.active_clients.get(user)
        if target:
            await target.send(MessageType.SYSTEM, {"message": f"You were kicked from room {room} by admin."})
        members = await self.rooms.get_members(room)
        for member in members:
            client = self.active_clients.get(member)
            if client:
                await client.send(MessageType.SYSTEM, {"message": f"{user} was kicked from the room."})
        await self.send(MessageType.ACK, {"action": "KICK"}, msg.msg_id)

    async def _on_msg(self, msg: ProtocolMessage) -> None:
        """
        MSG payload: { "room": "room_name", "content": "..." }
        """
        if not self.username:
            await self.send(MessageType.ERROR, {"error": "Authenticate first"})
            return
        room = msg.payload.get("room")
        content = msg.payload.get("content")
        if not isinstance(room, str) or not isinstance(content, str):
            await self.send(MessageType.ERROR, {"error": "Invalid message"})
            return
        members = await self.rooms.get_members(room)
        if self.username not in members:
            await self.send(MessageType.ERROR, {"error": f"You are not a member of room {room}"}, msg.msg_id)
            return
        now = time.time()
        ordered = await self.rooms.add_message(room, self.username, content, now)
        # Persist to DB
        self.db.persist_room_message(
            room_id=room,
            sender=self.username,
            content=content,
            sequence_number=ordered.sequence_number,
            timestamp=now,
        )
        # Broadcast to room members
        payload = {
            "room": room,
            "sender": self.username,
            "content": content,
            "timestamp": now,
            "sequence_number": ordered.sequence_number,
        }
        for member in members:
            client = self.active_clients.get(member)
            if client:
                await client.send(MessageType.MSG, payload)
        await self.send(MessageType.ACK, {"action": "MSG", "room": room}, msg.msg_id)

    async def _on_pmsg(self, msg: ProtocolMessage) -> None:
        """
        PMSG payload: { "to": "username", "content": "..." }
        """
        if not self.username:
            await self.send(MessageType.ERROR, {"error": "Authenticate first"})
            return
        to_user = msg.payload.get("to")
        content = msg.payload.get("content")
        if not isinstance(to_user, str) or not isinstance(content, str):
            await self.send(MessageType.ERROR, {"error": "Invalid message"})
            return
        now = time.time()
        self.db.persist_private_message(self.username, to_user, content, now)
        payload = {
            "sender": self.username,
            "receiver": to_user,
            "content": content,
            "timestamp": now,
        }
        # Deliver to receiver if connected
        target = self.active_clients.get(to_user)
        if target:
            await target.send(MessageType.PMSG, payload)
        # Optionally echo back to sender
        await self.send(MessageType.PMSG, payload)
        await self.send(MessageType.ACK, {"action": "PMSG", "to": to_user}, msg.msg_id)

    async def _on_list_rooms(self, msg: ProtocolMessage) -> None:  # type: ignore[override]
        rooms = await self.rooms.list_rooms()
        payload = [{"room": name, "members": members} for name, members in rooms]
        await self.send(MessageType.LIST_ROOMS, {"rooms": payload}, msg.msg_id)

    async def _on_list_users(self, msg: ProtocolMessage) -> None:  # type: ignore[override]
        # List active users
        users = list(self.active_clients.keys())
        await self.send(MessageType.LIST_USERS, {"users": users}, msg.msg_id)

    async def _on_file_send(self, msg: ProtocolMessage) -> None:
        """
        FILE_SEND payload:
        {
          "target": "room_or_user",
          "is_room": true | false,
          "filename": "...",
          "size": int
        }
        Server replies with ACK containing generated file_id.
        """
        if not self.username:
            await self.send(MessageType.ERROR, {"error": "Authenticate first"})
            return
        target = msg.payload.get("target")
        is_room = msg.payload.get("is_room")
        filename = msg.payload.get("filename")
        size = msg.payload.get("size")
        if not isinstance(target, str) or not isinstance(filename, str) or not isinstance(size, int):
            await self.send(MessageType.ERROR, {"error": "Invalid file metadata"})
            return
        if bool(is_room):
            members = await self.rooms.get_members(target)
            if self.username not in members:
                await self.send(MessageType.ERROR, {"error": f"You are not a member of room {target}"}, msg.msg_id)
                return
        incoming = await self.files.start_incoming(self.username, target, bool(is_room), filename, size)
        await self.send(
            MessageType.ACK,
            {"action": "FILE_SEND", "file_id": incoming.file_id},
            msg.msg_id,
        )

    async def _on_file_chunk(self, msg: ProtocolMessage) -> None:
        """
        FILE_CHUNK payload:
        {
          "file_id": "...",
          "data_b64": "..."   # base64-encoded bytes
        }
        """
        import base64

        file_id = msg.payload.get("file_id")
        data_b64 = msg.payload.get("data_b64")
        if not isinstance(file_id, str) or not isinstance(data_b64, str):
            await self.send(MessageType.ERROR, {"error": "Invalid file chunk"})
            return
        try:
            data = base64.b64decode(data_b64.encode("ascii"))
        except Exception:
            await self.send(MessageType.ERROR, {"error": "Bad base64 data"})
            return
        incoming = await self.files.append_chunk(file_id, data)
        if not incoming:
            await self.send(MessageType.ERROR, {"error": "Unknown file_id"})
            return
        await self.send(MessageType.ACK, {"action": "FILE_CHUNK", "file_id": file_id}, msg.msg_id)

    async def _on_file_end(self, msg: ProtocolMessage) -> None:
        """
        FILE_END payload:
        {
          "file_id": "..."
        }
        """
        file_id = msg.payload.get("file_id")
        if not isinstance(file_id, str):
            await self.send(MessageType.ERROR, {"error": "Invalid file end"})
            return
        finished = await self.files.finish_incoming(file_id)
        if not finished:
            await self.send(MessageType.ERROR, {"error": "Unknown file_id"})
            return

        # Persist metadata in DB
        self.db.persist_file_metadata(
            {
                "file_id": finished.file_id,
                "sender": finished.sender,
                "target": finished.target,
                "is_room": finished.is_room,
                "filename": finished.filename,
                "size": finished.size,
                "path": finished.path,
                "timestamp": time.time(),
            }
        )

        # Notify receivers
        import base64
        async def stream_file_to(client_conn, file_id, path, is_room, target_or_sender, filename, size):
            try:
                with open(path, "rb") as f:
                    while True:
                        chunk = f.read(4096)
                        if not chunk:
                            break
                        await client_conn.send(
                            MessageType.FILE_CHUNK,
                            {"file_id": file_id, "data_b64": base64.b64encode(chunk).decode("ascii")}
                        )
                        await asyncio.sleep(0.01)
                
                payload = {
                    "file_id": file_id,
                    "filename": filename,
                    "size": size,
                    "path": path,
                    "sender": finished.sender,
                    "target": target_or_sender,
                    "is_room": is_room,
                }
                if is_room:
                    payload["room"] = target_or_sender
                else:
                    payload["from"] = target_or_sender
                    payload["receiver"] = finished.target
                await client_conn.send(MessageType.FILE_END, payload)
            except Exception as e:
                print(f"Error streaming file: {e}")

        if finished.is_room:
            members = await self.rooms.get_members(finished.target)
            for member in members:
                client = self.active_clients.get(member)
                if client:
                    asyncio.create_task(stream_file_to(client, finished.file_id, finished.path, True, finished.target, finished.filename, finished.size))
        else:
            target_client = self.active_clients.get(finished.target)
            if target_client:
                asyncio.create_task(stream_file_to(target_client, finished.file_id, finished.path, False, finished.sender, finished.filename, finished.size))
        await self.send(MessageType.ACK, {"action": "FILE_END", "file_id": file_id}, msg.msg_id)


