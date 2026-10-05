import hashlib
import logging
from collections import deque

from metrics.node_metrics import metrics, MetricField
from utils.config_store import ConfigStore
from utils.exception_decorator import log_exceptions

DEDUP_WINDOW_SIZE = 10_000


class MessageStore:
    def __init__(self):
        self._incoming: dict[int, deque] = {}
        self._current_round: int = 0

        self._seen_hashes: set = set()
        self._seen_order: deque = deque(maxlen=DEDUP_WINDOW_SIZE)

        self._rtt_count: int = 0
        self._rtt_mean: float = 0.0
        self._in_counter: int = 0

        self._rounds_with_intake: set[int] = set()
        self._last_logged_received: int = -1

        self.fragments_per_model: int | None = None

    def is_duplicate(self, payload: bytes) -> bool:
        payload_hash = hashlib.sha256(payload).digest()
        if payload_hash in self._seen_hashes:
            return True

        # evict oldest when window is full
        if len(self._seen_order) == self._seen_order.maxlen:
            evicted_hash = self._seen_order[0]
            self._seen_hashes.discard(evicted_hash)

        self._seen_order.append(payload_hash)
        self._seen_hashes.add(payload_hash)
        return False

    def set_current_round(self, round_id: int) -> None:
        self._current_round = round_id
        self._last_logged_received = -1
        if ConfigStore.moq_enabled and round_id > 1:
            try:
                from communication.moq import get_moq_cache

                get_moq_cache().purge_round(round_id - 1)
            except Exception as e:
                logging.debug(f"MessageStore: MoQ cache purge failed: {e}")

    def enqueue_incoming(self, fragment: dict, round_id: int) -> None:
        if round_id < self._current_round:
            logging.debug(
                f"MessageStore: dropped past-round fragment (round={round_id}, current={self._current_round})"
            )
            return
        self._incoming.setdefault(round_id, deque()).append(fragment)
        self._rounds_with_intake.add(round_id)
        self._in_counter += 1

    def round_had_intake(self, round_id: int) -> bool:
        return round_id in self._rounds_with_intake

    @property
    def current_round(self) -> int:
        return self._current_round

    def drain_round(self, round_id: int) -> list[dict]:
        bucket = self._incoming.pop(round_id, None)
        return list(bucket) if bucket else []

    def incoming_count(self, round_id: int | None = None) -> int:
        if round_id is None:
            return sum(len(bucket) for bucket in self._incoming.values())
        return len(self._incoming.get(round_id, ()))

    def clear_rounds_before(self, round_id: int) -> int:
        stale_rounds = [r for r in self._incoming if r < round_id]
        for r in stale_rounds:
            del self._incoming[r]
        if ConfigStore.moq_enabled:
            try:
                from communication.moq import get_moq_cache

                get_moq_cache().purge_round(round_id)
            except Exception as e:
                logging.debug(f"MessageStore: MoQ cache purge failed: {e}")
        return len(stale_rounds)

    def record_rtt(self, rtt: float) -> None:
        if rtt < 0:
            return
        self._rtt_count += 1
        self._rtt_mean += (rtt - self._rtt_mean) / self._rtt_count
        metrics().set(MetricField.LAST_RTT, rtt)
        metrics().set(MetricField.AVG_RTT, self._rtt_mean)

    @log_exceptions
    def end_round(self, round_id: int) -> None:
        drained = len(self.drain_round(round_id))
        self.fragments_per_model = None
        if drained:
            logging.info(f"end_round({round_id}): drained {drained} late-arrival fragments")

    def expected_count(self, peer_count: int) -> int:
        from utils.config_store import ConfigStore

        effective_peers = max(1, round(peer_count * ConfigStore.partial_update_ratio))
        return effective_peers * (self.fragments_per_model or 0)

    def received_expected(self, peer_count: int, round_id: int) -> bool:
        expected = self.expected_count(peer_count)
        if expected == 0:
            return True
        received = self.incoming_count(round_id)
        if received != self._last_logged_received:
            received_pct = (received / expected) * 100
            logging.info(f"Received {received_pct:.1f}% of expected fragments ({received}/{expected})")
            self._last_logged_received = received
        return received >= expected

    @property
    def total_received(self) -> int:
        return self._in_counter

    def __repr__(self) -> str:
        return f"MessageStore(incoming={self.incoming_count()}, received={self._in_counter})"
