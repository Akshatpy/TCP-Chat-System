import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class RoomMessage:
    """
    In-memory representation of a room message with ordering metadata.
    """

    sequence_number: int
    sender: str
    content: str
    timestamp: float


@dataclass
class ChatRoom:
    name: str
    sequence_counter: int = 0
    members: Set[str] = field(default_factory=set)
    # history kept in memory for quick ordering verification / replay (optional)
    history: List[RoomMessage] = field(default_factory=list)

    def next_sequence(self) -> int:
        self.sequence_counter += 1
        return self.sequence_counter


class RoomManager:
    """
    Manages chat rooms, memberships, and per-room message ordering.
    """

    def __init__(self) -> None:
        self._rooms: Dict[str, ChatRoom] = {}
        # Protect all room operations with a single lock to avoid race conditions.
        self._lock = asyncio.Lock()

    async def ensure_room(self, room_name: str) -> ChatRoom:
        async with self._lock:
            room = self._rooms.get(room_name)
            if room is None:
                room = ChatRoom(name=room_name)
                self._rooms[room_name] = room
            return room

    async def join_room(self, room_name: str, username: str) -> ChatRoom:
        room = await self.ensure_room(room_name)
        async with self._lock:
            room.members.add(username)
            return room

    async def leave_room(self, room_name: str, username: str) -> None:
        async with self._lock:
            room = self._rooms.get(room_name)
            if not room:
                return
            room.members.discard(username)
            if not room.members:
                # Optionally clean up empty rooms from memory
                del self._rooms[room_name]

    async def remove_user_from_all_rooms(self, username: str) -> None:
        async with self._lock:
            empty_rooms = []
            for room_name, room in self._rooms.items():
                room.members.discard(username)
                if not room.members:
                    empty_rooms.append(room_name)
            for room_name in empty_rooms:
                del self._rooms[room_name]

    async def list_rooms(self) -> List[Tuple[str, int]]:
        async with self._lock:
            return [(room.name, len(room.members)) for room in self._rooms.values()]

    async def add_message(
        self,
        room_name: str,
        sender: str,
        content: str,
        timestamp: float,
    ) -> RoomMessage:
        """
        Allocate the next sequence number for the room and record the message.
        This guarantees strict per-room ordering.
        """
        room = await self.ensure_room(room_name)
        async with self._lock:
            seq = room.next_sequence()
            msg = RoomMessage(sequence_number=seq, sender=sender, content=content, timestamp=timestamp)
            room.history.append(msg)
            return msg

    async def get_members(self, room_name: str) -> Set[str]:
        async with self._lock:
            room = self._rooms.get(room_name)
            return set(room.members) if room else set()


