import logging
from typing import TYPE_CHECKING

from sphinxmix.SphinxClient import Relay_flag, Dest_flag, Surb_flag, receive_forward, pack_message
from sphinxmix.SphinxParams import SphinxParams

from communication.packages import deserialize_msg, PackageType
from communication.peer_session import find_session_by_surb
from metrics.node_metrics import metrics, MetricField
from utils.exception_decorator import log_exceptions

if TYPE_CHECKING:
    from communication.message_store import MessageStore
    from communication.peer_session import PeerSession
    from communication.sphinx.sphinx_router import SphinxRouter
    from communication.sphinx.sphinx_transport import SphinxTransport


class PacketRouter:
    def __init__(
            self,
            node_id: int,
            params: SphinxParams,
            sphinx_router: "SphinxRouter",
            message_store: "MessageStore",
            sessions: "dict[int, PeerSession]",
            sphinx_transport: "SphinxTransport",
    ):
        self._node_id = node_id
        self._params = params
        self._sphinx_router = sphinx_router
        self._message_store = message_store
        self._sessions = sessions
        self._sphinx_transport = sphinx_transport

    @log_exceptions
    async def on_packet_received(
        self, data: bytes, peer_id: int, moq_header=None
    ) -> None:
        metrics().increment(MetricField.TOTAL_MBYTES_RECEIVED, len(data) / 1048576)
        metrics().increment(MetricField.TOTAL_MSG_RECEIVED)

        if moq_header is not None:
            logging.debug(
                f"PacketRouter: Received packet with MoQ prefix: {moq_header.namespace} "
                f"track={moq_header.track_name} group={moq_header.group_id} obj={moq_header.object_id}"
            )

        try:
            routing, header, delta, mac_key = await self._sphinx_router.process_incoming(data)
        except Exception as e:
            logging.warning(f"PacketRouter: Failed to decrypt packet from peer {peer_id}: {e}")
            return

        try:
            await self._handle_routing_decision(routing, header, delta, mac_key)
        except Exception as e:
            logging.exception(f"PacketRouter: Error handling routing decision from peer {peer_id}: {e}")

    @log_exceptions
    async def _handle_routing_decision(self, routing, header, delta, mac_key) -> None:
        flag = routing[0]

        if flag == Relay_flag:
            await self._handle_relay(routing, header, delta)

        elif flag == Dest_flag:
            await self._handle_destination(delta, mac_key)

        elif flag == Surb_flag:
            await self._handle_surb(routing, delta)

        else:
            logging.warning(f"PacketRouter: Unexpected routing flag: {flag}")

    async def _handle_relay(self, routing, header, delta) -> None:
        next_hop = routing[1]
        msg = pack_message(self._params, (header, delta))

        await self._sphinx_transport.on_forward_packet(next_hop=next_hop, packet_data=msg)

    async def _handle_destination(self, delta, mac_key) -> None:
        _, payload_data = receive_forward(self._params, mac_key, delta)
        nymtuple, payload = payload_data

        fragment = deserialize_msg(payload)
        package_type = fragment.get("type")

        if package_type == PackageType.COVER:
            metrics().increment(MetricField.COVERS_RECEIVED)
            return

        if package_type == PackageType.PROBE:
            metrics().increment(MetricField.PROBES_RECEIVED)
            await self._sphinx_transport.on_surb_reply_needed(nymtuple=nymtuple)
            return

        is_dup = self._message_store.is_duplicate(payload)

        if is_dup:
            metrics().increment(MetricField.RECEIVED_DUPLICATE_MSG)
        else:
            round_id = fragment.get("round")
            if round_id is None:
                logging.debug("PacketRouter: model fragment missing round, dropping")
            else:
                metrics().increment(MetricField.FRAGMENTS_RECEIVED)
                self._message_store.enqueue_incoming(fragment, round_id)

        # ack even on dups, the sender's first ack may have been lost
        await self._sphinx_transport.on_surb_reply_needed(nymtuple=nymtuple)

    async def _handle_surb(self, routing, delta) -> None:
        surb_id = routing[2]
        metrics().increment(MetricField.SURB_RECEIVED)

        msg = self._sphinx_router.decrypt_surb(delta, surb_id)
        if msg is None:
            return

        session = find_session_by_surb(self._sessions, surb_id)
        if session is None:
            return
        rtt = session.record_surb_ack(surb_id)
        if rtt is not None:
            self._message_store.record_rtt(rtt)
