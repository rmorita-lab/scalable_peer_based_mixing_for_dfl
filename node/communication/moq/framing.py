"""
MoQ stream framing and packet extraction.

Handles packaging payloads with MoQ headers on unidirectional QUIC streams
and extracting frames from stream buffers.
"""

from typing import Tuple, Optional
import struct

from communication.moq.header import MoQHeader, MOQ_OBJECT_STREAM_TYPE
from communication.moq.namespace import TrackNamespace


def frame_message(header: MoQHeader, payload: bytes) -> bytes:
    """
    Frame a payload with its MoQ header.
    Wire layout:
        [Encoded MoQHeader] + [Payload bytes]
    """
    header_bytes = header.encode()
    return header_bytes + payload


def extract_frame(data: bytes) -> Optional[Tuple[MoQHeader, bytes, int]]:
    """
    Attempt to extract a complete MoQ frame from a buffer.

    Returns:
        tuple (MoQHeader, payload_bytes, total_bytes_consumed) if a full frame is available.
        None if more bytes are needed (incomplete frame).

    Also supports backward-compatibility fallback if data is in legacy 4-byte length prefix format.
    """
    if len(data) == 0:
        return None

    # Try decoding MoQHeader
    try:
        header, header_len = MoQHeader.decode(data, 0)
        total_len = header_len + header.payload_length
        if len(data) >= total_len:
            payload = data[header_len:total_len]
            return header, payload, total_len
        # Header decoded successfully, but waiting for full payload
        return None
    except Exception:
        # Check for legacy 4-byte big-endian length prefix format
        if len(data) >= 4:
            legacy_len = struct.unpack(">I", data[:4])[0]
            if len(data) >= 4 + legacy_len:
                legacy_payload = data[4 : 4 + legacy_len]
                # Synthesize a fallback MoQHeader for legacy packets
                fallback_header = MoQHeader(
                    namespace=TrackNamespace(("dfl", "legacy")),
                    track_name="packet",
                    group_id=0,
                    object_id=0,
                    payload_length=legacy_len,
                    publisher_priority=0,
                )
                return fallback_header, legacy_payload, 4 + legacy_len

    return None
