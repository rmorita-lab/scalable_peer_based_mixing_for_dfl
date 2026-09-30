"""
MoQ stream framing and packet extraction.

Handles packaging payloads with MoQ headers on unidirectional QUIC streams
and extracting frames from stream buffers.
"""

from typing import Tuple, Optional

from communication.moq.header import MoQHeader


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
        None if more bytes are needed (incomplete frame) or the header is malformed.

    NOTE: This function never falls back to legacy framing. Callers that need
    legacy 4-byte length-prefix decoding must handle that separately, gated on
    ConfigStore.moq_enabled being False.
    """
    if len(data) == 0:
        return None

    try:
        header, header_len = MoQHeader.decode(data, 0)
    except ValueError:
        # Buffer underflow (partial data) or malformed MoQ header.
        # Signal "need more data / discard" — do NOT fall through to any legacy path.
        return None

    total_len = header_len + header.payload_length
    if len(data) < total_len:
        # Header decoded successfully but payload hasn't fully arrived yet.
        return None

    payload = data[header_len:total_len]
    return header, payload, total_len
