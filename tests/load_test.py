import asyncio
import time
import uuid
from typing import List

from server.protocol import encode_message, decode_message, MessageType
from server.tls import create_client_ssl_context


class LoadTestClient:
    def __init__(self, host: str, port: int, username: str) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.reader: asyncio.StreamReader
        self.writer: asyncio.StreamWriter

    async def connect_and_login(self) -> None:
        self.reader, self.writer = await asyncio.open_connection(
            self.host,
            self.port,
            ssl=create_client_ssl_context(),
            server_hostname="localhost",
        )
        # Register or login
        for action in ("register", "login"):
            payload = {"action": action, "username": self.username, "password": "test"}
            self.writer.write(encode_message(MessageType.AUTH, payload, str(uuid.uuid4())))
            await self.writer.drain()
            while True:
                msg = decode_message(await self.reader.readline())
                if msg.type == MessageType.SYSTEM.value:
                    continue
                if msg.type == MessageType.AUTH_OK.value:
                    return
                if action == "login":
                    raise RuntimeError(f"Authentication failed for {self.username}: {msg.payload.get('error')}")
                break

    async def send_messages(self, room: str, count: int) -> float:
        # join room
        self.writer.write(
            encode_message(
                MessageType.JOIN,
                {"room": room},
                str(uuid.uuid4()),
            )
        )
        await self.writer.drain()
        while True:
            msg = decode_message(await self.reader.readline())
            if msg.type == MessageType.SYSTEM.value:
                continue
            break

        start = time.time()
        for i in range(count):
            self.writer.write(
                encode_message(
                    MessageType.MSG,
                    {"room": room, "content": f"msg-{self.username}-{i}"},
                    str(uuid.uuid4()),
                )
            )
        await self.writer.drain()
        end = time.time()
        return (end - start) / max(count, 1)


async def run_load_test(
    host: str = "127.0.0.1",
    port: int = 8888,
    num_clients: int = 10,
    messages_per_client: int = 20,
) -> None:
    clients: List[LoadTestClient] = [LoadTestClient(host, port, f"user{i}") for i in range(num_clients)]
    await asyncio.gather(*(c.connect_and_login() for c in clients))
    latencies = await asyncio.gather(*(c.send_messages("load_room", messages_per_client) for c in clients))
    avg_latency = sum(latencies) / len(latencies)
    print(f"Average client-side send latency per message: {avg_latency * 1000:.2f} ms")


if __name__ == "__main__":
    asyncio.run(run_load_test())


