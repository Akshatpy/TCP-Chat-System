## Secure Multi-Room Chat System (TCP, asyncio, MongoDB)

### Architecture (Text Diagram)

- **CLI / Web Clients**
  - CLI: `client/client.py` (asyncio TCP client, custom JSON-line protocol)
  - Web: `web/index.html` connects to `web/bridge.py` (WebSocket), which bridges to TCP server
- **TCP Chat Server** (`server/server.py`)
  - Uses `asyncio.start_server` for concurrent clients
  - Per-connection logic in `server/client_handler.py`
  - Per-room ordering and membership managed by `server/room_manager.py`
  - File transfers handled by `server/file_transfer.py`
  - MongoDB integration / persistence in `server/db.py`
- **MongoDB Atlas**
  - `users`, `chatrooms`, `messages`, `private_messages`, `files` collections

- Core message types (see `server/protocol.py`):
  - `AUTH` / `AUTH_OK` / `AUTH_FAIL`
  - `JOIN`, `LEAVE`
  - `MSG` (room message with strict sequence ordering)
  - `PMSG` (private 1:1 message)
  - `FILE_SEND`, `FILE_CHUNK`, `FILE_END`
  - `ACK` (for operations and file transfer phases)
  - `LIST_ROOMS`, `LIST_USERS`
  - `SYSTEM`, `ERROR`
### How to Run

#### 1. Install Dependencies

```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

#### 1a. Generate TLS Certificates

The TCP server and CLI/load-test clients use TLS. Generate the local self-signed certificate pair before starting the server:

```bash
python gen_cert.py
```

#### 2. Start TCP Chat Server

```bash
python -m server.server
```

Server listens on `127.0.0.1:8888`.
The CLI client, load test, and web bridge connect to it over TLS using the generated `server.crt`.

#### 3. Run CLI Client

```bash
python -m client.client
```

Follow prompts to login/register, then use commands:

- `/join <room>`
- `/leave <room>`
- `/rooms`
- `/users`
- `/msg <room> <text>`
- `/pmsg <user> <text>`
- `/sendfile_room <room> <path>`
- `/sendfile_user <user> <path>`
- `/quit`

#### 4. Run Web Bridge + Frontend

Terminal 1 – TCP server:

```bash
python -m server.server
```

Terminal 2 – WebSocket bridge:

```bash
python -m web.bridge
```

Then open `web/index.html` in a browser (e.g. using VSCode Live Server or a simple HTTP server).
The page connects via WebSocket to the bridge, which forwards messages to the TCP server.




