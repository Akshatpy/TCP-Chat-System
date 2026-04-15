import asyncio
import os
from typing import Dict

from .db import Database
from .env_loader import load_dotenv_file
from .room_manager import RoomManager
from .file_transfer import FileTransferManager
from .client_handler import ClientSession
from .tls import create_server_ssl_context


load_dotenv_file()


class ChatServer:
    """
    Async TCP chat server entrypoint.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8888) -> None:
        self.host = host
        self.port = port
        self.db = Database()
        self.rooms = RoomManager()
        self.files = FileTransferManager()
        # Maps username -> active client session
        self.active_clients: Dict[str, ClientSession] = {}
        self._server: asyncio.AbstractServer | None = None

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        session = ClientSession(
            reader=reader,
            writer=writer,
            db=self.db,
            rooms=self.rooms,
            files=self.files,
            active_clients=self.active_clients,
        )
        await session.handle()

    async def start(self) -> None:
        ssl_context = create_server_ssl_context()
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port, ssl=ssl_context)
        addrs = ", ".join(str(sock.getsockname()) for sock in self._server.sockets or [])
        print(f"Chat TCP server listening on {addrs}", flush=True)
        async with self._server:
            await self._server.serve_forever()


async def main() -> None:
    server = ChatServer()
    admin_username = os.getenv("CHAT_ADMIN_USERNAME")
    admin_password = os.getenv("CHAT_ADMIN_PASSWORD")
    if admin_username and admin_password and not server.db.verify_user(admin_username, admin_password):
        server.db.create_user(admin_username, admin_password)
    elif not admin_username or not admin_password:
        print("Admin credentials are not configured. Set CHAT_ADMIN_USERNAME and CHAT_ADMIN_PASSWORD to enable moderator login.")
    await server.start()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Server shutting down...")
    except Exception as e:
        print(f"Error starting server: {e}")


