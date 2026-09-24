"""
MoQ Object Header implementation based on moq-dev/moq.

Defines the header structure carrying namespace prefixes, track identifiers,
group & object sequence IDs, priorities, and payload lengths.
Enables prefix-based filtering, caching, and relay operations without
inspecting payload data.
"""

from __future__ import annotations
import struct
from dataclasses import dataclass
from typing import Tuple, Union, Optional

from communication.moq.varint import encode_varint, decode_varint
from communication.moq.namespace import TrackNamespace, Path


# MoQ Stream / Message Type IDs
# 0x00: OBJECT_DATAGRAM / OBJECT
# 0x04: STREAM_HEADER_SUBGROUP / OBJECT_STREAM
MOQ_OBJECT_STREAM_TYPE = 0x04


@dataclass(frozen=True)
class MoQHeader:
    """
    MoQ Object Header with hierarchical namespace prefix.

    Attributes:
        namespace: TrackNamespace representing the hierarchical prefix tuple (e.g. ("dfl", "round_1", "node_0")).
        track_name: Identifier of the track within the namespace (e.g. "weights", "gradients", "probe", "cover").
        group_id: Group sequence number (in DFL: corresponds to training round ID).
        object_id: Object sequence number within the group (in DFL: corresponds to chunk/part index).
        publisher_priority: Priority byte (0 = highest priority).
        payload_length: Length in bytes of the following object payload.
        message_type: MoQ message / stream type identifier (default 0x04).
    """

    namespace: TrackNamespace
    track_name: str
    group_id: int
    object_id: int
    payload_length: int
    publisher_priority: int = 0
    message_type: int = MOQ_OBJECT_STREAM_TYPE

    def cache_key(self) -> str:
        """
        Generate a unique cache key for this object.
        Useful for relay caching, deduplication, and subscriber lookups.
        Example: 'dfl/round_1/node_0/weights:group_1:obj_0'
        """
        return f"{self.namespace.path}/{self.track_name}:g{self.group_id}:o{self.object_id}"

    def matches_namespace_prefix(
        self, prefix: Union[TrackNamespace, str, Tuple[str, ...]]
    ) -> bool:
        """Check if this header's namespace matches a given namespace prefix."""
        return self.namespace.has_prefix(prefix)

    def encode(self) -> bytes:
        """
        Encode this header to MoQ wire format:
        - message_type: varint (1 byte for 0x04)
        - namespace: encoded TrackNamespace
        - track_name: varint length + utf-8 bytes
        - group_id: varint
        - object_id: varint
        - publisher_priority: uint8 (1 byte)
        - payload_length: varint
        """
        buf = bytearray()
        # Message type
        buf.extend(encode_varint(self.message_type))
        # Track Namespace (tuple-encoded with varint count and length-prefixed parts)
        buf.extend(self.namespace.encode())
        # Track Name
        track_bytes = self.track_name.encode("utf-8")
        buf.extend(encode_varint(len(track_bytes)))
        buf.extend(track_bytes)
        # Group ID (round)
        buf.extend(encode_varint(self.group_id))
        # Object ID (chunk/part)
        buf.extend(encode_varint(self.object_id))
        # Publisher Priority
        buf.append(self.publisher_priority & 0xFF)
        # Payload Length
        buf.extend(encode_varint(self.payload_length))

        return bytes(buf)

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> Tuple[MoQHeader, int]:
        """
        Decode a MoQHeader from wire bytes.

        Returns:
            tuple (MoQHeader, bytes_consumed)
        """
        start = offset
        # Message type
        msg_type, consumed = decode_varint(data, offset)
        offset += consumed

        # Track Namespace
        namespace, consumed = TrackNamespace.decode(data, offset)
        offset += consumed

        # Track Name
        track_len, consumed = decode_varint(data, offset)
        offset += consumed
        if offset + track_len > len(data):
            raise ValueError("Buffer underflow reading track name")
        track_name = data[offset : offset + track_len].decode("utf-8", errors="replace")
        offset += track_len

        # Group ID
        group_id, consumed = decode_varint(data, offset)
        offset += consumed

        # Object ID
        object_id, consumed = decode_varint(data, offset)
        offset += consumed

        # Priority
        if offset >= len(data):
            raise ValueError("Buffer underflow reading priority")
        priority = data[offset]
        offset += 1

        # Payload Length
        payload_len, consumed = decode_varint(data, offset)
        offset += consumed

        header = cls(
            namespace=namespace,
            track_name=track_name,
            group_id=group_id,
            object_id=object_id,
            payload_length=payload_len,
            publisher_priority=priority,
            message_type=msg_type,
        )

        return header, (offset - start)


def create_dfl_header(
    node_id: int,
    package_type_name: str,
    round_id: int,
    chunk_idx: int,
    payload_length: int,
    priority: int = 0,
) -> MoQHeader:
    """
    Helper to construct a MoQHeader for DFL data with hierarchical namespace prefix.

    Example hierarchy:
        - Namespace: 'dfl/node_{node_id}/{package_type_name}'
          (allows subscribing to 'dfl', 'dfl/node_{node_id}', or 'dfl/node_{node_id}/model')
        - Track Name: 'weights' (for model) or package_type_name
        - Group ID: round_id
        - Object ID: chunk_idx
    """
    namespace = TrackNamespace(("dfl", f"node_{node_id}", package_type_name.lower()))
    track_name = "weights" if package_type_name.lower() == "model_part" else package_type_name.lower()
    return MoQHeader(
        namespace=namespace,
        track_name=track_name,
        group_id=round_id,
        object_id=chunk_idx,
        payload_length=payload_length,
        publisher_priority=priority,
    )
