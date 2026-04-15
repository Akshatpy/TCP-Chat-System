import json
from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, Optional


class MessageType(str, Enum):
    AUTH = "AUTH"  # login / signup
    AUTH_OK = "AUTH_OK"
    AUTH_FAIL = "AUTH_FAIL"
    JOIN = "JOIN"
    LEAVE = "LEAVE"
    MSG = "MSG"
    PMSG = "PMSG"
    FILE_SEND = "FILE_SEND"
    FILE_CHUNK = "FILE_CHUNK"
    FILE_END = "FILE_END"
    ACK = "ACK"
    ERROR = "ERROR"
    SYSTEM = "SYSTEM"
    LIST_ROOMS = "LIST_ROOMS"
    LIST_USERS = "LIST_USERS"
    KICK = "KICK"


@dataclass
class ProtocolMessage:
    """
    Application-level protocol message transported over a TCP stream.

    Each message is encoded as a single JSON object terminated by '\\n'.
    This keeps framing simple and robust.
    """

    type: str
    payload: Dict[str, Any]
    # Optional correlation id for matching ACKs / responses
    msg_id: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"))

    @staticmethod
    def from_json(data: str) -> "ProtocolMessage":
        obj = json.loads(data)
        if not isinstance(obj, dict):
            raise ValueError("Protocol message must be a JSON object")
        msg_type = obj.get("type")
        payload = obj.get("payload", {})
        msg_id = obj.get("msg_id")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        return ProtocolMessage(type=msg_type, payload=payload, msg_id=msg_id)


def encode_message(msg_type: MessageType, payload: Dict[str, Any], msg_id: Optional[str] = None) -> bytes:
    """
    Encode a protocol message as bytes ready to be written to the TCP stream.
    """
    msg = ProtocolMessage(type=msg_type.value, payload=payload, msg_id=msg_id)
    # Messages are delimited by newline for easy framing
    return (msg.to_json() + "\n").encode("utf-8")


def decode_message(line: bytes) -> ProtocolMessage:
    """
    Decode a single JSON line into a ProtocolMessage.
    """
    text = line.decode("utf-8").strip()
    if not text:
        raise ValueError("Empty protocol message")
    return ProtocolMessage.from_json(text)

        