import asyncio
import logging
import os
import secrets
import struct

from aioquic.asyncio import connect, serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import StreamDataReceived, ConnectionTerminated, HandshakeCompleted

from metrics.node_metrics import metrics, MetricField
from utils.config_store import ConfigStore

from communication.moq import (
    MoQHeader,
    TrackNamespace,
    frame_message,
    extract_frame,
)

QUIC_IDLE_TIMEOUT = 180.0
RECONNECT_FAIL_LIMIT = 3


def _extract_message_from_buffer(
    buffer: dict[int, bytes], event: StreamDataReceived
) -> tuple[bytes, Optional[MoQHeader]] | None:
    stream_id = event.stream_id
    if stream_id not in buffer:
        buffer[stream_id] = b""
    buffer[stream_id] += event.data

    if event.end_stream:
        raw_stream_data = buffer.pop(stream_id, b"")
        result = extract_frame(raw_stream_data)
        if result is not None:
            header, payload, _ = result
            return payload, header
        # Fallback for legacy 4-byte big-endian framing
        if len(raw_stream_data) >= 4:
            length = struct.unpack(">I", raw_stream_data[:4])[0]
            fallback_hdr = MoQHeader(
                namespace=TrackNamespace(("dfl", "legacy")),
                track_name="packet",
                group_id=0,
                object_id=0,
                payload_length=length,
            )
            return raw_stream_data[4 : 4 + length], fallback_hdr
    return None


async def _keepalive_loop(protocol: QuicConnectionProtocol) -> None:
    # jittered ~15s PING to keep idle links alive
    ping_id = 0
    try:
        while True:
            await asyncio.sleep(15.0 + secrets.SystemRandom().uniform(-2.0, 2.0))
            ping_id += 1
            protocol._quic.send_ping(ping_id)
            protocol.transmit()
    except asyncio.CancelledError:
        pass


class QuicServerProtocol(QuicConnectionProtocol):
    def __init__(self, *args, server: "QuicServer", **kwargs):
        super().__init__(*args, **kwargs)
        self._server = server
        self._buffer: dict[int, bytes] = {}
        self._peer_id: int | None = None
        self._ka_task: asyncio.Task | None = None

        _init = self._quic._initialize

        def _initialize(peer_cid, _i=_init):
            _i(peer_cid)
            self._quic.tls._request_client_certificate = True

        self._quic._initialize = _initialize

    def _extract_peer_id(self) -> int:
        try:
            peer_cert = self._quic.tls._peer_certificate
            if peer_cert:
                from cryptography import x509

                for attr in peer_cert.subject:
                    if attr.oid == x509.oid.NameOID.COMMON_NAME:
                        cn = attr.value  # node_5
                        return int(cn.split("_")[1])
        except Exception as e:
            logging.warning(f"Failed to extract peer_id from certificate: {e}")
        return -1

    def _cancel_keepalive(self) -> None:
        if self._ka_task is not None:
            self._ka_task.cancel()
            self._ka_task = None

    def connection_lost(self, exc):
        self._cancel_keepalive()
        super().connection_lost(exc)

    def quic_event_received(self, event):
        if isinstance(event, HandshakeCompleted):
            if self._ka_task is None:
                self._ka_task = asyncio.create_task(_keepalive_loop(self))
            if self._peer_id is None:
                self._peer_id = self._extract_peer_id()
                if self._peer_id >= 0:
                    self._server._incoming_active[self._peer_id] = self
        elif isinstance(event, StreamDataReceived):
            self._handle_stream_data(event)
        elif isinstance(event, ConnectionTerminated):
            self._cancel_keepalive()
            if self._peer_id is not None and self._peer_id >= 0:
                if self._server._incoming_active.get(self._peer_id) is self:
                    self._server._incoming_active.pop(self._peer_id, None)
                level = logging.DEBUG if self._server.is_shutting_down() else logging.WARNING
                logging.log(level, f"Incoming connection from peer {self._peer_id} lost: {event.reason_phrase}")
                if not self._server.is_shutting_down():
                    if self._server._peer_node is not None:
                        if event.reason_phrase == "":
                            self._server._peer_node.mark_peer_unreachable(self._peer_id)
                    self._server._spawn_reconnect_loop(self._peer_id)

    def _handle_stream_data(self, event: StreamDataReceived):
        extracted = _extract_message_from_buffer(self._buffer, event)
        if extracted:
            payload, moq_header = extracted
            asyncio.create_task(
                self._server._handle_message(
                    payload,
                    self._peer_id if self._peer_id is not None else -1,
                    moq_header=moq_header,
                )
            )


class QuicClientProtocol(QuicConnectionProtocol):
    def __init__(self, *args, server: "QuicServer", peer_id: int, **kwargs):
        super().__init__(*args, **kwargs)
        self._server = server
        self._peer_id = peer_id
        self._buffer: dict[int, bytes] = {}
        self._ka_task: asyncio.Task | None = None

    def _cancel_keepalive(self) -> None:
        if self._ka_task is not None:
            self._ka_task.cancel()
            self._ka_task = None

    def connection_lost(self, exc):
        self._cancel_keepalive()
        super().connection_lost(exc)

    def quic_event_received(self, event):
        if isinstance(event, HandshakeCompleted):
            if self._ka_task is None:
                self._ka_task = asyncio.create_task(_keepalive_loop(self))
        elif isinstance(event, StreamDataReceived):
            self._handle_stream_data(event)
        elif isinstance(event, ConnectionTerminated):
            self._cancel_keepalive()
            registered = self._peer_id in self._server._connections
            if registered and not self._server.is_shutting_down():
                level = logging.WARNING
            else:
                level = logging.DEBUG
            logging.log(level, f"Connection to peer {self._peer_id} lost: {event.reason_phrase}")
            if registered:
                del self._server._connections[self._peer_id]
            if not self._server.is_shutting_down() and self._server._peer_node is not None:
                if event.reason_phrase == "":
                    self._server._peer_node.mark_peer_unreachable(self._peer_id)
                metrics().set(MetricField.ACTIVE_PEERS, len(self._server._connections))
            if self._peer_id in self._server._connection_cms:
                del self._server._connection_cms[self._peer_id]
            if not self._server.is_shutting_down():
                self._server._spawn_reconnect_loop(self._peer_id)

    def _handle_stream_data(self, event: StreamDataReceived):
        extracted = _extract_message_from_buffer(self._buffer, event)
        if extracted:
            payload, moq_header = extracted
            asyncio.create_task(
                self._server._handle_message(
                    payload,
                    self._peer_id,
                    moq_header=moq_header,
                )
            )


class QuicServer:
    def __init__(self, node_id: int, port: int, peers: dict):
        self.node_id = node_id
        self.port = port
        self.peers = peers

        self._server = None
        self._connections: dict[int, QuicConnectionProtocol] = {}
        metrics().set(MetricField.ACTIVE_PEERS, 0)
        self._connection_cms: dict[int, any] = {}
        self._connection_locks: dict[int, asyncio.Lock] = {}
        self._server_config: QuicConfiguration | None = None

        self._packet_router = None
        self._peer_node = None

        self._reconnect_tasks: dict[int, asyncio.Task] = {}
        self._incoming_active: dict[int, QuicServerProtocol] = {}
        self._dial_attempts: dict[int, int] = {}

    def set_packet_router(self, router) -> None:
        assert router is not None, "packet_router must not be None"
        self._packet_router = router

    def set_peer_node(self, node) -> None:
        assert node is not None, "peer_node must not be None"
        self._peer_node = node

    def _i_dial(self, peer_id: int) -> bool:
        my_join = ConfigStore.join_schedule.get(self.node_id, 0)
        peer_join = ConfigStore.join_schedule.get(peer_id, 0)
        if my_join != peer_join:
            return my_join > peer_join
        # pair parity decides who dials to split load evenly
        lo, hi = sorted((self.node_id, peer_id))
        dialer = lo if (lo + hi) % 2 == 0 else hi
        return dialer == self.node_id

    def has_link(self, peer_id: int) -> bool:
        return peer_id in self._connections or peer_id in self._incoming_active

    def _load_certificates(self):
        cert_path = os.environ.get("CERT_PATH", "/config/certs")

        self._server_config = QuicConfiguration(
            is_client=False,
            alpn_protocols=["dfl"],
            idle_timeout=QUIC_IDLE_TIMEOUT,
        )
        self._server_config.load_cert_chain(
            certfile=f"{cert_path}/node_{self.node_id}.pem",
            keyfile=f"{cert_path}/node_{self.node_id}-key.pem",
        )
        self._server_config.load_verify_locations(f"{cert_path}/ca.pem")

    async def start(self):
        self._load_certificates()

        self._server = await serve(
            host="127.0.0.1",
            port=self.port,
            configuration=self._server_config,
            create_protocol=lambda *args, **kwargs: QuicServerProtocol(*args, server=self, **kwargs),
        )
        logging.info(f"QUIC server listening on port {self.port}")

    async def connect_peers(self):
        rng = secrets.SystemRandom()
        await asyncio.sleep(5.0 + rng.uniform(0.0, 10.0))

        target = {pid for pid in self.peers if pid != self.node_id and self._i_dial(pid)}
        if not target:
            return

        for pid in target:
            if pid not in self._connection_locks:
                self._connection_locks[pid] = asyncio.Lock()
            self._spawn_reconnect_loop(pid)

        logging.info(f"Background reconnect tasks active for {len(target)} peers")

    def _spawn_reconnect_loop(self, peer_id: int) -> None:
        if self.is_shutting_down():
            return
        if peer_id == self.node_id or peer_id not in self.peers:
            return
        if not self._i_dial(peer_id):
            return
        existing = self._reconnect_tasks.get(peer_id)
        if existing is not None and not existing.done():
            return
        self._reconnect_tasks[peer_id] = asyncio.create_task(self._reconnect_loop(peer_id))

    async def _reconnect_loop(self, peer_id: int) -> None:
        try:
            host, port = self.peers[peer_id]
            rng = secrets.SystemRandom()
            await asyncio.sleep(rng.uniform(0, 1.0))
            backoff = 1.0
            while not self.is_shutting_down() and peer_id not in self._connections:
                current_round = int(metrics().get_all().get("current_round", 0) or 0)
                peer_join_round = ConfigStore.join_schedule.get(peer_id, 0)
                if peer_join_round > current_round:  # not joined yet
                    await asyncio.sleep(30.0)
                    continue
                # UNREACHABLE from resend exhaustion, back off the QUIC to probe frequency
                if self._peer_node is not None and self._peer_node.sensed_unreachable(peer_id):
                    await asyncio.sleep(30.0)
                    continue
                await self._connect_peer(peer_id, host, port)
                if peer_id in self._connections:
                    return
                if self._peer_node is not None and self._dial_attempts.get(peer_id, 0) >= RECONNECT_FAIL_LIMIT:
                    self._peer_node.mark_peer_unreachable(peer_id)
                await asyncio.sleep(backoff + rng.uniform(0, 0.5))
                backoff = min(backoff * 2, 8.0)
        except asyncio.CancelledError:
            pass

    async def _connect_peer(self, peer_id: int, host: str, port: int):
        if peer_id not in self._connection_locks:
            self._connection_locks[peer_id] = asyncio.Lock()
        async with self._connection_locks[peer_id]:
            if peer_id in self._connections:
                return

            try:
                client_config = QuicConfiguration(
                    is_client=True,
                    alpn_protocols=["dfl"],
                    idle_timeout=QUIC_IDLE_TIMEOUT,
                    server_name=f"node_{peer_id}",
                )
                cert_path = os.environ.get("CERT_PATH", "/config/certs")
                client_config.load_cert_chain(
                    certfile=f"{cert_path}/node_{self.node_id}.pem",
                    keyfile=f"{cert_path}/node_{self.node_id}-key.pem",
                )
                client_config.load_verify_locations(f"{cert_path}/ca.pem")

                cm = connect(
                    host=host,
                    port=port,
                    configuration=client_config,
                    create_protocol=lambda *args, **kwargs: QuicClientProtocol(
                        *args, server=self, peer_id=peer_id, **kwargs
                    ),
                )
                result = await asyncio.wait_for(cm.__aenter__(), timeout=10.0)
                protocol = result[1] if isinstance(result, tuple) else result
                self._connections[peer_id] = protocol
                metrics().set(MetricField.ACTIVE_PEERS, len(self._connections))
                self._connection_cms[peer_id] = cm
                self._dial_attempts.pop(peer_id, None)
                logging.info(f"Connected to peer {peer_id} at {host}:{port}")
            except Exception as e:
                attempts = self._dial_attempts.get(peer_id, 0)
                self._dial_attempts[peer_id] = attempts + 1
                level = logging.INFO if attempts == 0 else logging.DEBUG
                logging.log(level, f"Failed to connect to peer {peer_id}: {e}")

    async def _ensure_connection(self, peer_id: int) -> QuicConnectionProtocol | None:
        if peer_id in self._connections:
            return self._connections[peer_id]

        if peer_id not in self.peers:
            return None

        if peer_id not in self._connection_locks:
            self._connection_locks[peer_id] = asyncio.Lock()

        host, port = self.peers[peer_id]
        await self._connect_peer(peer_id, host, port)
        return self._connections.get(peer_id)

    async def _handle_message(
        self, message: bytes, peer_id: int = -1, moq_header: Optional[MoQHeader] = None
    ):
        try:
            await self._packet_router.on_packet_received(
                data=message, peer_id=peer_id, moq_header=moq_header
            )
        except Exception as e:
            logging.exception(f"QuicServer: on_packet_received failed for peer {peer_id}: {e}")

    def is_shutting_down(self) -> bool:
        return self._peer_node is not None and self._peer_node._shutting_down

    async def _send_raw(
        self, peer_id: int, message: bytes, moq_header: Optional[MoQHeader] = None
    ):
        if self._i_dial(peer_id):
            protocol = self._connections.get(peer_id)
            if protocol is None:
                protocol = await self._ensure_connection(peer_id)
                if protocol is None:
                    raise ConnectionError(f"No connection to peer {peer_id}")
        else:
            protocol = self._incoming_active.get(peer_id)
            if protocol is None:
                raise ConnectionError(f"No inbound connection from peer {peer_id}")

        stream_id = protocol._quic.get_next_available_stream_id(is_unidirectional=True)
        if moq_header is not None:
            framed = frame_message(moq_header, message)
        elif ConfigStore.moq_enabled:
            default_hdr = MoQHeader(
                namespace=TrackNamespace(("dfl", f"node_{self.node_id}")),
                track_name="packet",
                group_id=0,
                object_id=0,
                payload_length=len(message),
            )
            framed = frame_message(default_hdr, message)
        else:
            framed = struct.pack(">I", len(message)) + message

        protocol._quic.send_stream_data(stream_id, framed, end_stream=True)
        protocol.transmit()

    async def send_to_peer(
        self, peer_id: int, message: bytes, moq_header: Optional[MoQHeader] = None
    ):
        if peer_id not in self.peers:
            return
        try:
            await self._send_raw(peer_id, message, moq_header=moq_header)
            metrics().increment(MetricField.TOTAL_MSG_SENT)
            metrics().increment(MetricField.TOTAL_MBYTES_SENT, len(message) / 1048576)
        except Exception as e:
            logging.debug(f"Send to peer {peer_id} failed: {e}")

    async def close_all_connections(self):
        tasks = list(self._reconnect_tasks.values())
        self._reconnect_tasks.clear()
        for t in tasks:
            t.cancel()
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=5.0,
                )
            except TimeoutError:
                pass

        cms = list(self._connection_cms.values())
        self._connection_cms.clear()
        self._connections.clear()
        self._incoming_active.clear()
        metrics().set(MetricField.ACTIVE_PEERS, 0)

        for cm in cms:
            try:
                await asyncio.wait_for(cm.__aexit__(None, None, None), timeout=2.0)
            except Exception:
                pass

        if self._server:
            self._server.close()

        logging.info("All QUIC connections closed.")
