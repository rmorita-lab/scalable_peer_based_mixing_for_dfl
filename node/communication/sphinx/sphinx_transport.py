import asyncio
import logging
import secrets
import time
from functools import partial
from typing import TYPE_CHECKING

from sphinxmix.SphinxParams import SphinxParams

from communication.mixing import Mixer
from communication.packages import serialize_msg, format_probe_package
from communication.peer_session import PeerState
from communication.quic_server import QuicServer
from communication.sphinx.sphinx_router import SphinxRouter
from metrics.node_metrics import metrics, MetricField
from utils.config_store import ConfigStore
from utils.exception_decorator import log_exceptions

if TYPE_CHECKING:
    from communication.cover_generator import CoverGenerator as _CoverGen
    from communication.message_store import MessageStore
    from communication.peer_session import PeerSession


class SphinxTransport:
    def __init__(
            self,
            node_id,
            port,
            peers,
            message_store: "MessageStore | None" = None,
            sessions: "dict[int, PeerSession] | None" = None,
            neighbors: list[int] | None = None,
            topology: dict[int, list[int]] | None = None,
    ):
        self._node_id = node_id
        self._port = port
        self._peers = peers
        self._neighbors: set[int] = set(neighbors) if neighbors else set(peers.keys())

        self._message_store = message_store
        self._sessions = sessions or {}

        self._peer = QuicServer(
            node_id=node_id,
            port=port,
            peers=peers,
        )

        self._mixer = Mixer(is_live=self._peer.has_link)
        self.n_fragments_per_model = None  # set later on from the model size

        self._params = SphinxParams(header_len=192, body_len=ConfigStore.sphinx_body_len, k=16, dest_len=16)

        self.sphinx_router = SphinxRouter(
            node_id,
            self._params,
            sessions=self._sessions,
            is_live=self._peer.has_link,
            topology=topology or {},
        )

        self._cover_generator: "_CoverGen | None" = None

        if ConfigStore.mix_enabled and not topology:
            logging.error(
                f"SphinxTransport[{node_id}]: mix_enabled=True but topology is empty! "
                "No messages or covers can be routed. Check topology configuration."
            )

    @property
    def params(self):
        return self._params

    @property
    def server(self):
        return self._peer

    @property
    def quic_server(self):
        return self._peer

    @property
    def mixer(self):
        return self._mixer

    @log_exceptions
    async def received_all_expected_fragments(self, round_id: int):
        if self._message_store is None:
            raise RuntimeError("MessageStore not configured")
        return self._message_store.received_expected(self.exchange_send_count(), round_id)

    @log_exceptions
    async def transport_all_acked(self):
        return self.sphinx_router.router_all_acked()

    def set_fragments_per_model(self, n_fragments: int):
        self.n_fragments_per_model = n_fragments
        if self._message_store is not None:
            self._message_store.fragments_per_model = n_fragments

    def expected_fragment_count(self) -> int:
        if self._message_store is not None:
            return self._message_store.expected_count(self.exchange_send_count())
        return self.exchange_send_count() * (self.n_fragments_per_model or 0)

    def _exchange_candidates(self) -> list[int]:
        if ConfigStore.mix_enabled:
            return self.sphinx_router.get_exchange_targets(self._node_id)
        return list(self._neighbors)

    def _get_exchange_peers(self) -> list[int]:
        candidates = self._exchange_candidates()
        peers = [p for p in candidates if self._sessions[p].state != PeerState.UNREACHABLE]
        if not peers:
            logging.warning(
                f"SphinxTransport[{self._node_id}]: send list empty "
                f"(candidates={len(candidates)}, mix_enabled={ConfigStore.mix_enabled})"
            )
        return peers

    def exchange_send_count(self) -> int:
        return sum(1 for p in self._exchange_candidates() if self._sessions[p].state != PeerState.UNREACHABLE)

    def exchange_peer_count(self) -> int:
        return sum(1 for p in self._exchange_candidates() if self._sessions[p].is_reachable)

    async def close_all_connections(self):
        await self._mixer.stop()
        await self._peer.close_all_connections()
        self.sphinx_router.close()

    def set_cover_generator(self, cover_gen: "_CoverGen") -> None:
        self._cover_generator = cover_gen
        self._mixer._cover_generator = cover_gen

    async def wait_until_mesh_healthy(self, timeout: float) -> set[int]:
        my_join = ConfigStore.my_join_round()
        required = {
            pid for pid in self._neighbors if pid != self._node_id and ConfigStore.join_schedule.get(pid, 0) <= my_join
        }
        if not required:
            return set()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            missing = {pid for pid in required if not self._peer.has_link(pid)}
            if not missing:
                return set()
            await asyncio.sleep(0.5)
        return {pid for pid in required if not self._peer.has_link(pid)}

    @log_exceptions
    async def start(self):
        await self._peer.start()
        await self._peer.connect_peers()
        await self._mixer.start()

    @log_exceptions
    async def send_probes(self) -> int:
        unreachable = [pid for pid, s in self._sessions.items() if s.state == PeerState.UNREACHABLE]
        if not unreachable:
            return 0
        for peer_id in unreachable:
            payload = serialize_msg(format_probe_package(secrets.token_bytes(ConfigStore.nr_cover_bytes)))
            path, msg_bytes, timestamp_callback = await self.generate_path(
                payload, peer_id, cover=True, serialize=False
            )
            update_metrics_task = partial(metrics().increment, MetricField.PROBES_SENT)
            send_msg_task = partial(self.send, path, msg_bytes, timestamp_callback)
            await self._mixer.queue_item(send_msg_task, update_metrics_task, next_hop=path[0])
        return len(unreachable)

    @log_exceptions
    async def send_to_peers(self, message):
        peers = self._get_exchange_peers()
        if not peers:
            logging.warning(
                f"SphinxTransport[{self._node_id}]: send_to_peers() has no peers, "
                f"0 fragments will be queued this round (mix_enabled={ConfigStore.mix_enabled})"
            )
        if ConfigStore.partial_update_ratio < 1.0 and peers:
            select_count = max(1, round(len(peers) * ConfigStore.partial_update_ratio))
            peers = secrets.SystemRandom().sample(peers, select_count)
        round_id = message.get("round", 0)
        chunk_idx = message.get("part_idx", 0)
        payload = serialize_msg(message)
        for peer_id in peers:
            path, msg_bytes, timestamp_callback = await self.generate_path(
                payload, peer_id, cover=False, serialize=False, round_id=round_id
            )
            moq_hdr = None
            if ConfigStore.moq_enabled:
                from communication.moq import create_dfl_header

                moq_hdr = create_dfl_header(
                    node_id=self._node_id,
                    package_type_name="model_part",
                    round_id=round_id,
                    chunk_idx=chunk_idx,
                    payload_length=len(msg_bytes),
                )
            update_metrics_task = partial(metrics().increment, MetricField.FRAGMENTS_SENT)
            send_msg_task = partial(self.send, path, msg_bytes, timestamp_callback, moq_header=moq_hdr)
            await self._mixer.queue_item(send_msg_task, update_metrics_task, next_hop=path[0])
        return len(peers)

    async def generate_path(
            self, message, target_node: int, cover: bool, serialize: bool = True, round_id: int | None = None
    ):
        payload = message
        if serialize:
            payload = serialize_msg(message)
        path, msg_bytes, timestamp_callback, _, _ = await self.sphinx_router.create_forward_msg(
            target_node, payload, cover, round_id=round_id
        )
        return path, msg_bytes, timestamp_callback

    @log_exceptions
    async def send(self, path, msg_bytes, timestamp_callback, moq_header=None):
        if timestamp_callback is not None:
            timestamp_callback()
        await self._peer.send_to_peer(path[0], msg_bytes, moq_header=moq_header)

    async def on_forward_packet(self, next_hop: int, packet_data: bytes) -> None:
        forward_hdr = None
        if ConfigStore.moq_enabled:
            from communication.moq import MoQHeader, TrackNamespace

            forward_hdr = MoQHeader(
                namespace=TrackNamespace(("dfl", f"node_{self._node_id}", "relay")),
                track_name="forward",
                group_id=0,
                object_id=0,
                payload_length=len(packet_data),
            )
        send_task = partial(self._peer.send_to_peer, next_hop, packet_data, moq_header=forward_hdr)
        update_metrics_task = partial(metrics().increment, MetricField.FORWARDED)
        await self._mixer.queue_item(send_task, update_metrics_task, next_hop=next_hop)

    async def on_surb_reply_needed(self, nymtuple: tuple) -> None:
        msg_bytes, first_hop = self.sphinx_router.create_surb_reply(nymtuple)
        send_task = partial(self._peer.send_to_peer, first_hop, msg_bytes)
        update_metrics_task = partial(metrics().increment, MetricField.SURB_REPLIED)
        await self._mixer.queue_item(send_task, update_metrics_task, next_hop=first_hop)
