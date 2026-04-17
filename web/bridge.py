import asyncio
import os
import json
import websockets
from typing import Any
from server.protocol import encode_message, decode_message, ProtocolMessage
from server.protocol import MessageType
from server.env_loader import load_dotenv_file
from server.tls import create_client_ssl_context


load_dotenv_file()


def _resolve_bridge_target_host() -> str:
    # 0.0.0.0 is valid for server bind, but invalid as a client connect target.
    host = os.getenv("CHAT_SERVER_HOST", "127.0.0.1")
    if host in {"0.0.0.0", "::"}:
        return "localhost"
    return host


async def tcp_bridge_handler(websocket: Any, path: str | None = None) -> None:  # type: ignore[override]
    """
    WebSocket <-> TCP bridge.
    Browser speaks the same JSON protocol; the bridge streams bytes to/from the TCP chat server.
    """
    target_host = _resolve_bridge_target_host()
    target_port = int(os.getenv("CHAT_SERVER_PORT", "8888"))
    ssl_context = create_client_ssl_context()
    try:
        reader, writer = await asyncio.open_connection(
            target_host,
            target_port,
            ssl=ssl_context,
            server_hostname=target_host,
        )
    except Exception as e:
        await websocket.send(
            json.dumps(
                {
                    "type": "ERROR",
                    "payload": {
                        "error": f"Bridge could not connect to TCP server at {target_host}:{target_port}: {e}",
                    },
                }
            )
        )
        return

    async def ws_to_tcp() -> None:
        async for text in websocket:
            try:
                obj = json.loads(text)
            except Exception:
                await websocket.send(json.dumps({"type": "ERROR", "payload": {"error": "bad JSON"}}))
                continue
            # Forward as encoded protocol line
            t = obj.get("type")
            payload = obj.get("payload", {})
            msg_id = obj.get("msg_id")
            writer.write(encode_message(MessageType(t), payload, msg_id))
            await writer.drain()

    async def tcp_to_ws() -> None:
        while True:
            line = await reader.readline()
            if not line:
                break
            msg: ProtocolMessage = decode_message(line)
            await websocket.send(msg.to_json())

    try:
        await asyncio.gather(ws_to_tcp(), tcp_to_ws())
    finally:
        writer.close()
        await writer.wait_closed()


async def main() -> None:
    print("WebSocket bridge listening on ws://127.0.0.1:8765")
    async with websockets.serve(tcp_bridge_handler, "127.0.0.1", 8765):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    asyncio.run(main())


