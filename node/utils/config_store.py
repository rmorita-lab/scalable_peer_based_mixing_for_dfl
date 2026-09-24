import json
import os


def _env(key: str, default):
    val = os.environ.get(key)
    if val is None:
        return default
    if isinstance(default, bool):
        return val.lower() in ("true", "1", "yes")
    if isinstance(default, int):
        return int(val)
    if isinstance(default, float):
        return float(val)
    return val


def _env_required(key: str, kind):
    if key not in os.environ:
        raise RuntimeError(f"{key} not set; manager must broadcast it")
    val = os.environ[key]
    if kind is bool:
        return val.lower() in ("true", "1", "yes")
    if kind is int:
        return int(val)
    if kind is float:
        return float(val)
    if kind is str:
        return val
    raise RuntimeError(f"_env_required: unsupported kind {kind} for {key}")


def _env_int_list_required(key: str) -> list[int]:
    if key not in os.environ:
        raise RuntimeError(f"{key} not set; manager must broadcast it")
    val = os.environ[key]
    if val == "":
        return []
    return [int(part) for part in val.split(",") if part]


def _env_json_dict_required(key: str) -> dict[int, list[int]]:
    if key not in os.environ:
        raise RuntimeError(f"{key} not set; manager must broadcast it")
    val = os.environ[key]
    if val == "":
        return {}
    raw = json.loads(val)
    return {int(k): v for k, v in raw.items()}


def _env_json_int_dict_required(key: str) -> dict[int, int]:
    if key not in os.environ:
        raise RuntimeError(f"{key} not set; manager must broadcast it")
    val = os.environ[key]
    if val == "":
        return {}
    raw = json.loads(val)
    return {int(k): int(v) for k, v in raw.items()}


def _env_json_endpoints_required(key: str) -> dict[int, tuple[str, int]]:
    if key not in os.environ:
        raise RuntimeError(f"{key} not set; manager must broadcast it")
    val = os.environ[key]
    if val == "":
        return {}
    raw = json.loads(val)
    return {int(node_id): (endpoint[0], int(endpoint[1])) for node_id, endpoint in raw.items()}


class ConfigStore:
    model_name: str = _env_required("MODEL_NAME", str)
    dataset: str = _env_required("DATASET", str)
    node_id: int = _env_required("NODE_ID", int)
    n_nodes: int = _env_required("N_NODES", int)
    n_rounds: int = _env_required("N_ROUNDS", int)
    batch_size: int = _env_required("BATCH_SIZE", int)
    torch_threads: int = _env_required("TORCH_THREADS", int)
    dirichlet_alpha: float = _env_required("DIRICHLET_ALPHA", float)
    mix_enabled: bool = _env_required("MIX_ENABLED", bool)
    mix_mu: float = _env_required("MIX_MU", float)
    max_hops: int = _env_required("MAX_HOPS", int)

    port: int = _env_required("PORT", int)
    controller_url: str = _env_required("CONTROLLER_URL", str)
    resend_time: int = _env_required("RESEND_TIME", int)
    push_metric_interval: int = _env_required("PUSH_METRIC_INTERVAL", int)
    stall_timeout: int = _env_required("STALL_TIMEOUT", int)
    startup_connect_timeout: int = _env_required("STARTUP_CONNECT_TIMEOUT", int)
    completeness_floor: float = _env_required("COMPLETENESS_FLOOR", float)
    n_batches_per_round: int = _env_required("N_BATCHES_PER_ROUND", int)
    mix_std: float = _env_required("MIX_STD", float)
    mix_shuffle: bool = _env_required("MIX_SHUFFLE", bool)
    mix_outbox_size: int = _env_required("MIX_OUTBOX_SIZE", int)
    nr_cover_bytes: int = _env_required("NR_COVER_BYTES", int)
    pause_training: bool = _env_required("PAUSE_TRAINING", bool)
    cache_covers: bool = _env_required("CACHE_COVERS", bool)
    max_cover_cache: int = _env_required("MAX_COVER_CACHE", int)
    quantization_bits: int = _env_required("QUANTIZATION_BITS", int)

    sphinx_body_len: int = _env_required("SPHINX_BODY_LEN", int)
    aggregation_algorithm: str = _env_required("AGGREGATION_ALGORITHM", str)
    krum_byzantine_fraction: float = _env_required("KRUM_BYZANTINE_FRACTION", float)
    partial_update_ratio: float = _env_required("PARTIAL_UPDATE_RATIO", float)
    attack_type: str = _env_required("ATTACK_TYPE", str)
    n_byzantine: int = _env_required("N_BYZANTINE", int)
    attack_noise_sigma: float = _env_required("ATTACK_NOISE_SIGMA", float)
    join_schedule: dict[int, int] = _env_json_int_dict_required("JOIN_SCHEDULE")
    exit_schedule: dict[int, int] = _env_json_int_dict_required("EXIT_SCHEDULE")
    neighbors: list[int] = _env_int_list_required("NEIGHBORS")
    topology: dict[int, list[int]] = _env_json_dict_required("TOPOLOGY")
    peer_endpoints: dict[int, tuple[str, int]] = _env_json_endpoints_required("PEER_ENDPOINTS")

    moq_enabled: bool = _env("MOQ_ENABLED", False)

    cert_path: str = _env("CERT_PATH", "/config/certs")

    @classmethod
    def my_join_round(cls) -> int:
        return cls.join_schedule.get(cls.node_id, 0)

    @classmethod
    def my_exit_round(cls) -> int:
        return cls.exit_schedule.get(cls.node_id, 0)
