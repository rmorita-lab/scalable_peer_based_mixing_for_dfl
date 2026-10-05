"""
Media over QUIC (MoQ) Transport modules for DFL.

Based on moq-dev/moq specifications:
- Hierarchical Track Namespace tuples with prefix matching
- Sized & prioritized Object headers
- Varint-based compact wire framing
"""

from communication.moq.varint import encode_varint, decode_varint, varint_size
from communication.moq.namespace import TrackNamespace, Path, to_tuple, from_tuple
from communication.moq.header import MoQHeader, create_dfl_header, MOQ_OBJECT_STREAM_TYPE
from communication.moq.framing import frame_message, extract_frame
from communication.moq.cache import MoQCache, MoQCacheEntry, get_moq_cache, reset_moq_cache

__all__ = [
    "encode_varint",
    "decode_varint",
    "varint_size",
    "TrackNamespace",
    "Path",
    "to_tuple",
    "from_tuple",
    "MoQHeader",
    "create_dfl_header",
    "MOQ_OBJECT_STREAM_TYPE",
    "frame_message",
    "extract_frame",
    "MoQCache",
    "MoQCacheEntry",
    "get_moq_cache",
    "reset_moq_cache",
]
