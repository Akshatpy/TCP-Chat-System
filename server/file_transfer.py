import asyncio
import os
import uuid
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class IncomingFile:
    """
    Tracks the state of an in-progress file transfer for a client.
    """

    file_id: str
    sender: str
    target: str  # room or username
    is_room: bool
    filename: str
    size: int
    received_bytes: int = 0
    path: Optional[str] = None
    chunks: bytearray = field(default_factory=bytearray)


class FileTransferManager:
    """
    Manages chunk-based file transfers over the TCP protocol.
    """

    def __init__(self, base_dir: str = "data/files") -> None:
        self._incoming: Dict[str, IncomingFile] = {}
        self._lock = asyncio.Lock()
        self.base_dir = base_dir
        os.makedirs(self.base_dir, exist_ok=True)

    async def start_incoming(
        self,
        sender: str,
        target: str,
        is_room: bool,
        filename: str,
        size: int,
    ) -> IncomingFile:
        async with self._lock:
            file_id = str(uuid.uuid4())
            incoming = IncomingFile(
                file_id=file_id,
                sender=sender,
                target=target,
                is_room=is_room,
                filename=filename,
                size=size,
            )
            self._incoming[file_id] = incoming
            return incoming

    async def append_chunk(self, file_id: str, data: bytes) -> Optional[IncomingFile]:
        async with self._lock:
            incoming = self._incoming.get(file_id)
            if not incoming:
                return None
            incoming.chunks.extend(data)
            incoming.received_bytes += len(data)
            return incoming

    async def finish_incoming(self, file_id: str) -> Optional[IncomingFile]:
        async with self._lock:
            incoming = self._incoming.pop(file_id, None)
            if not incoming:
                return None
            # Persist to disk
            safe_name = f"{incoming.file_id}_{os.path.basename(incoming.filename)}"
            path = os.path.join(self.base_dir, safe_name)
            with open(path, "wb") as f:
                f.write(incoming.chunks)
            incoming.path = path
            return incoming


