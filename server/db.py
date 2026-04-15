import os
from typing import Any, Dict, List, Optional

from pymongo import MongoClient, ASCENDING
from pymongo.collection import Collection
from pymongo.database import Database
import bcrypt
import datetime


class Database:
    """
    Thin wrapper around MongoDB (Atlas) for this chat system.
    """
    def __init__(self, uri: Optional[str] = None, db_name: str = "secure_chat") -> None:
        uri = uri or os.getenv("MONGODB_URI", "mongodb://127.0.0.1:27017")
        self._client = MongoClient(uri, serverSelectionTimeoutMS=5000, tlsAllowInvalidCertificates=True)
        try:
            self._client.admin.command("ping")
        except Exception as e:
            raise RuntimeError(
                "Could not connect to MongoDB. Set MONGODB_URI or start a local server."
            ) from e
        self._db: Database = self._client[db_name]
        self._init_indexes()

    @property
    def users(self) -> Collection:
        return self._db["users"]

    @property
    def chatrooms(self) -> Collection:
        return self._db["chatrooms"]

    @property
    def messages(self) -> Collection:
        return self._db["messages"]

    @property
    def private_messages(self) -> Collection:
        return self._db["private_messages"]

    @property
    def files(self) -> Collection:
        return self._db["files"]

    def _init_indexes(self) -> None:
        self.users.create_index("username", unique=True)
        self.chatrooms.create_index("room_id", unique=True)
        self.messages.create_index([("room_id", ASCENDING), ("sequence_number", ASCENDING)])
        self.private_messages.create_index([("sender", ASCENDING), ("receiver", ASCENDING), ("timestamp", ASCENDING)])
        self.files.create_index("file_id", unique=True)

    # User management
    def create_user(self, username: str, password: str) -> bool:
        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        try:
            self.users.insert_one(
                {
                    "username": username,
                    "password_hash": password_hash,
                    "active_status": False,
                }
            )
            return True
        except Exception:
            return False

    def verify_user(self, username: str, password: str) -> bool:
        user = self.users.find_one({"username": username})
        if not user:
            return False
        return bcrypt.checkpw(password.encode("utf-8"), user["password_hash"])

    def set_user_active(self, username: str, active: bool) -> None:
        self.users.update_one({"username": username}, {"$set": {"active_status": active}})

    # Room / message persistence
    def persist_room_message(
        self,
        room_id: str,
        sender: str,
        content: str,
        sequence_number: int,
        timestamp: float,
    ) -> None:
        self.messages.insert_one(
            {
                "room_id": room_id,
                "sender": sender,
                "content": content,
                "timestamp": datetime.datetime.fromtimestamp(timestamp),
                "sequence_number": sequence_number,
            }
        )

    def persist_private_message(self, sender: str, receiver: str, content: str, timestamp: float) -> None:
        self.private_messages.insert_one(
            {
                "sender": sender,
                "receiver": receiver,
                "content": content,
                "timestamp": datetime.datetime.fromtimestamp(timestamp),
            }
        )

    def persist_file_metadata(self, metadata: Dict[str, Any]) -> None:
        self.files.insert_one(metadata)


