"""
RFC 9000 / MoQ Variable-length Integer (varint) Encoding & Decoding.

Follows the variable-length integer encoding specification from QUIC (RFC 9000 §16)
used throughout MoQ Transport (draft-ietf-moq-transport) and moq-dev/moq.
"""

from typing import Tuple


VARINT_MAX_1BYTE = 63
VARINT_MAX_2BYTES = 16383
VARINT_MAX_4BYTES = 1073741823
VARINT_MAX_8BYTES = 4611686018427387903


def encode_varint(value: int) -> bytes:
    """Encode an integer as a QUIC/MoQ variable-length integer."""
    if value < 0:
        raise ValueError(f"Varint value cannot be negative: {value}")
    if value <= VARINT_MAX_1BYTE:
        return bytes([value])
    elif value <= VARINT_MAX_2BYTES:
        return bytes([0x40 | ((value >> 8) & 0x3F), value & 0xFF])
    elif value <= VARINT_MAX_4BYTES:
        return bytes([
            0x80 | ((value >> 24) & 0x3F),
            (value >> 16) & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ])
    elif value <= VARINT_MAX_8BYTES:
        return bytes([
            0xC0 | ((value >> 56) & 0x3F),
            (value >> 48) & 0xFF,
            (value >> 40) & 0xFF,
            (value >> 32) & 0xFF,
            (value >> 24) & 0xFF,
            (value >> 16) & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ])
    else:
        raise ValueError(f"Varint value exceeds maximum 62-bit integer: {value}")


def decode_varint(data: bytes, offset: int = 0) -> Tuple[int, int]:
    """
    Decode a QUIC/MoQ variable-length integer from bytes.

    Returns:
        tuple (value, bytes_consumed)
    """
    if offset >= len(data):
        raise ValueError("Buffer underflow while reading varint prefix")

    first = data[offset]
    prefix = (first & 0xC0) >> 6

    if prefix == 0:
        return first & 0x3F, 1
    elif prefix == 1:
        if offset + 2 > len(data):
            raise ValueError("Buffer underflow while reading 2-byte varint")
        val = ((first & 0x3F) << 8) | data[offset + 1]
        return val, 2
    elif prefix == 2:
        if offset + 4 > len(data):
            raise ValueError("Buffer underflow while reading 4-byte varint")
        val = (
            ((first & 0x3F) << 24)
            | (data[offset + 1] << 16)
            | (data[offset + 2] << 8)
            | data[offset + 3]
        )
        return val, 4
    else:
        if offset + 8 > len(data):
            raise ValueError("Buffer underflow while reading 8-byte varint")
        val = (
            ((first & 0x3F) << 56)
            | (data[offset + 1] << 48)
            | (data[offset + 2] << 40)
            | (data[offset + 3] << 32)
            | (data[offset + 4] << 24)
            | (data[offset + 5] << 16)
            | (data[offset + 6] << 8)
            | data[offset + 7]
        )
        return val, 8


def varint_size(value: int) -> int:
    """Return the encoded size in bytes of a varint."""
    if value <= VARINT_MAX_1BYTE:
        return 1
    elif value <= VARINT_MAX_2BYTES:
        return 2
    elif value <= VARINT_MAX_4BYTES:
        return 4
    elif value <= VARINT_MAX_8BYTES:
        return 8
    else:
        raise ValueError(f"Varint value exceeds maximum: {value}")
