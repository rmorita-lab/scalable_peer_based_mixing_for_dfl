"""
Track Namespace and Path implementation based on moq-dev/moq.

Implements the MoQ Transport Track Namespace specification (draft-ietf-moq-transport)
and moq-dev/moq's Path/Namespace abstraction:
- Namespaces are ordered N-tuples of strings/byte-strings (N <= 32).
- Hierarchical slash-separated path representation with escaping (\\/ and \\\\).
- Prefix matching operations for routing, subscription scopes, and cache keys.
- Compact varint-based wire serialization/deserialization.
"""

from __future__ import annotations
from typing import Tuple, List, Union, Optional
from communication.moq.varint import encode_varint, decode_varint


MAX_NAMESPACE_PARTS = 32


def to_tuple(path: str) -> Tuple[str, ...]:
    """
    Parse a slash-delimited path into a tuple of parts, honoring escapes.
    Matches moq-dev/moq's `to_tuple` logic in rs/moq-net/src/ietf/namespace.rs.
    """
    if not path:
        return ()

    # Strip leading and trailing slashes if not escaped
    trimmed = path.strip("/")
    if not trimmed:
        return ()

    parts: List[str] = []
    part: List[str] = []
    chars = iter(trimmed)
    
    for ch in chars:
        if ch == "/":
            parts.append("".join(part))
            part = []
        elif ch == "\\":
            next_ch = next(chars, None)
            if next_ch in ("/", "\\"):
                part.append(next_ch)
            elif next_ch is not None:
                part.append("\\")
                part.append(next_ch)
            else:
                part.append("\\")
        else:
            part.append(ch)
            
    parts.append("".join(part))
    return tuple(parts)


def from_tuple(parts: Tuple[str, ...]) -> str:
    """
    Format a tuple of parts into an escaped slash-delimited path.
    Matches moq-dev/moq's `from_tuple` logic in rs/moq-net/src/ietf/namespace.rs.
    """
    escaped_parts: List[str] = []
    for part in parts:
        res = []
        for ch in part:
            if ch in ("/", "\\"):
                res.append("\\")
            res.append(ch)
        escaped_parts.append("".join(res))
    return "/".join(escaped_parts)


class TrackNamespace:
    """
    Represents a MoQ Track Namespace as a hierarchical tuple of namespace elements.

    Can be constructed from:
    - a slash-delimited string path: e.g. "dfl/models/node_0"
    - a tuple/list of string parts: e.g. ("dfl", "models", "node_0")
    """

    def __init__(self, value: Union[str, Tuple[str, ...], List[str], TrackNamespace]):
        if isinstance(value, TrackNamespace):
            self._parts = value._parts
            self._path = value._path
        elif isinstance(value, str):
            self._parts = to_tuple(value)
            self._path = from_tuple(self._parts)
        elif isinstance(value, (tuple, list)):
            self._parts = tuple(str(p) for p in value)
            if len(self._parts) > MAX_NAMESPACE_PARTS:
                raise ValueError(
                    f"Namespace parts ({len(self._parts)}) exceed maximum allowed ({MAX_NAMESPACE_PARTS})"
                )
            self._path = from_tuple(self._parts)
        else:
            raise TypeError(f"Invalid TrackNamespace source type: {type(value)}")

        if len(self._parts) > MAX_NAMESPACE_PARTS:
            raise ValueError(
                f"Namespace parts ({len(self._parts)}) exceed maximum allowed ({MAX_NAMESPACE_PARTS})"
            )

    @property
    def parts(self) -> Tuple[str, ...]:
        """Return the tuple of parts."""
        return self._parts

    @property
    def path(self) -> str:
        """Return the escaped slash-delimited path representation."""
        return self._path

    def __len__(self) -> int:
        return len(self._parts)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TrackNamespace):
            return self._parts == other._parts
        if isinstance(other, (tuple, list)):
            return self._parts == tuple(other)
        if isinstance(other, str):
            return self == TrackNamespace(other)
        return False

    def __hash__(self) -> int:
        return hash(self._parts)

    def __str__(self) -> str:
        return self._path

    def __repr__(self) -> str:
        return f"TrackNamespace({self._parts!r})"

    def has_prefix(self, prefix: Union[TrackNamespace, str, Tuple[str, ...], List[str]]) -> bool:
        """
        Check if this namespace has the given prefix.
        Prefix matching is element-aware (segment-aware), ensuring e.g.
        'foo/bar' has prefix 'foo', but 'foobar' does NOT have prefix 'foo'.
        """
        if not isinstance(prefix, TrackNamespace):
            prefix = TrackNamespace(prefix)

        prefix_parts = prefix.parts
        if len(prefix_parts) > len(self._parts):
            return False

        return self._parts[: len(prefix_parts)] == prefix_parts

    def strip_prefix(
        self, prefix: Union[TrackNamespace, str, Tuple[str, ...], List[str]]
    ) -> Optional[TrackNamespace]:
        """
        Strip the prefix from this namespace if present.
        Returns a new TrackNamespace with the remaining suffix, or None if no match.
        """
        if not isinstance(prefix, TrackNamespace):
            prefix = TrackNamespace(prefix)

        if not self.has_prefix(prefix):
            return None

        remaining = self._parts[len(prefix.parts) :]
        return TrackNamespace(remaining)

    def join(self, *parts: str) -> TrackNamespace:
        """Create a new TrackNamespace by appending parts."""
        combined = list(self._parts)
        for p in parts:
            if "/" in p:
                combined.extend(to_tuple(p))
            else:
                combined.append(p)
        return TrackNamespace(tuple(combined))

    def encode(self) -> bytes:
        """
        Encode this namespace to MoQ wire format:
        - count (varint): number of parts
        - for each part:
            - length (varint)
            - part bytes (utf-8)
        """
        buf = bytearray()
        buf.extend(encode_varint(len(self._parts)))
        for part in self._parts:
            part_bytes = part.encode("utf-8")
            buf.extend(encode_varint(len(part_bytes)))
            buf.extend(part_bytes)
        return bytes(buf)

    @classmethod
    def decode(cls, data: bytes, offset: int = 0) -> Tuple[TrackNamespace, int]:
        """
        Decode a TrackNamespace from MoQ wire format.

        Returns:
            tuple (TrackNamespace, bytes_consumed)
        """
        start = offset
        count, consumed = decode_varint(data, offset)
        offset += consumed

        if count > MAX_NAMESPACE_PARTS:
            raise ValueError(
                f"Decoded namespace part count {count} exceeds MAX_NAMESPACE_PARTS {MAX_NAMESPACE_PARTS}"
            )

        parts: List[str] = []
        for _ in range(count):
            part_len, consumed = decode_varint(data, offset)
            offset += consumed
            if offset + part_len > len(data):
                raise ValueError("Buffer underflow reading namespace part bytes")
            part_bytes = data[offset : offset + part_len]
            offset += part_len
            parts.append(part_bytes.decode("utf-8", errors="replace"))

        return cls(tuple(parts)), (offset - start)


# Alias Path to TrackNamespace for parity with moq-dev/moq
Path = TrackNamespace
