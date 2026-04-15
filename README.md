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

### Protocol Design

- Transport: raw TCP streams
- Framing: **one JSON object per line**, `\\n`-delimited
- Generic structure:

```json
{
  "type": "MSG_TYPE",
  "payload": { ... },
  "msg_id": "optional-correlation-id"
}
```

- Core message types (see `server/protocol.py`):
  - `AUTH` / `AUTH_OK` / `AUTH_FAIL`
  - `JOIN`, `LEAVE`
  - `MSG` (room message with strict sequence ordering)
  - `PMSG` (private 1:1 message)
  - `FILE_SEND`, `FILE_CHUNK`, `FILE_END`
  - `ACK` (for operations and file transfer phases)
  - `LIST_ROOMS`, `LIST_USERS`
  - `SYSTEM`, `ERROR`

### Example Payloads

- **Authenticate**

```json
{
  "type": "AUTH",
  "payload": { "action": "login", "username": "alice", "password": "secret" },
  "msg_id": "uuid"
}
```

- **Join Room**

```json
{
  "type": "JOIN",
  "payload": { "room": "lobby" },
  "msg_id": "uuid"
}
```

- **Room Message**

```json
{
  "type": "MSG",
  "payload": { "room": "lobby", "content": "hello world" },
  "msg_id": "uuid"
}
```

- **Private Message**

```json
{
  "type": "PMSG",
  "payload": { "to": "bob", "content": "hi" },
  "msg_id": "uuid"
}
```

- **File Transfer (metadata)**

```json
{
  "type": "FILE_SEND",
  "payload": {
    "target": "lobby",
    "is_room": true,
    "filename": "doc.pdf",
    "size": 12345
  },
  "msg_id": "uuid"
}
```

Then multiple `FILE_CHUNK` messages with base64-encoded data and a final `FILE_END`.

### Message Ordering

- Each room is tracked by `RoomManager` (`server/room_manager.py`)
- On every `MSG`:
  - A single `asyncio.Lock` serializes room state operations
  - The room's `sequence_counter` is incremented
  - The message is stored with `sequence_number` and appended to in-memory history
  - The same `sequence_number` is used when persisting to MongoDB and when broadcasting
- This guarantees **per-room, strictly increasing, gap-free ordering** for delivered messages.

### MongoDB Setup

1. Create a MongoDB Atlas cluster or run local MongoDB.
2. Set environment variable:

```bash
export MONGODB_URI="your-mongodb-connection-string"
```

3. Collections are auto-created with indexes by `Database` (`server/db.py`):
   - `users(username, password_hash, active_status)`
   - `chatrooms(room_id, room_name, members)` (simplified in this implementation)
   - `messages(room_id, sender, content, timestamp, sequence_number)`
   - `private_messages(sender, receiver, content, timestamp)`
   - `files(file_id, sender, receiver/room, metadata, path)`

Passwords are hashed using **bcrypt**.

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

### Performance Testing

`tests/load_test.py` simulates multiple clients sending messages to a shared room.

Run:

```bash
python -m tests.load_test
```

It reports **average client-side send latency per message**. You can adjust:

- `num_clients`
- `messages_per_client`

inside `run_load_test()` to explore scaling characteristics.

### Failure Handling & Security Notes

- Disconnects: when a TCP stream closes, `ClientSession.handle()` cleans up the session and marks the user inactive.
- Invalid / malformed JSON or payload shapes: server responds with `ERROR` message and continues handling.
- Partial file transfers:
  - If a file never receives `FILE_END`, the in-memory record is eventually discarded when the connection closes.
  - Only completed files are flushed to disk and MongoDB.
- Auth:
  - Passwords are stored only as bcrypt hashes.
  - Basic username/password authentication, no JWT; session is bound to the TCP connection.

