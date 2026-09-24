import json

from pydantic import BaseModel, Field, model_validator


class ExperimentConfig(BaseModel):
    model_name: str = Field(default="lenet5")
    dataset: str = Field(default="mnist")
    n_nodes: int = Field(default=10, ge=1, le=100)
    n_rounds: int = Field(default=10, ge=1, le=100)
    batch_size: int = Field(default=64, ge=16, le=256)
    torch_threads: int = Field(
        default=1, ge=1, le=64, description="Cap on torch intra-op threads; 1 leaves cores free for the mixer loop"
    )
    dirichlet_alpha: float = Field(default=10.0, ge=0.1, le=100.0)
    mix_enabled: bool = Field(default=True)
    mix_mu: float = Field(default=0.1, ge=0.001, le=1.0)
    max_hops: int = Field(default=2, ge=1, le=5)
    topology_type: str = Field(default="full_mesh", description="Topology type: full_mesh or circulant")
    graph_degree: int = Field(default=4, ge=2, description="Node degree for circulant graph")
    mix_outbox_size: int = Field(default=10, ge=1, le=200, description="Shuffle queue size per mixing step")
    aggregation_algorithm: str = Field(default="fedavg", description="Aggregation algorithm: fedavg or krum")
    quantization_bits: int = Field(default=8, description="Quantization bit width (8 or 32)")
    krum_byzantine_fraction: float = Field(
        default=0.33, ge=0.0, le=1.0, description="Assumed fraction of Byzantine nodes for Krum"
    )
    attack_type: str = Field(
        default="none", description="Byzantine attack type: none, label_flip, gaussian_noise, or sign_flip"
    )
    n_byzantine: int = Field(default=0, ge=0, description="Number of Byzantine (adversarial) nodes")
    attack_noise_sigma: float = Field(
        default=0.1, ge=0.0, le=10.0, description="Std of gaussian_noise attack as a fraction of weight std"
    )
    partial_update_ratio: float = Field(
        default=1.0, gt=0.0, le=1.0, description="Fraction of peers each fragment is sent to"
    )
    n_join_late: int = Field(default=0, ge=0, description="Number of nodes that join late")
    n_exit_early: int = Field(default=0, ge=0, description="Number of nodes that exit early")
    port: int = Field(default=8000)
    resend_time: int = Field(default=90)
    push_metric_interval: int = Field(default=10)
    stall_timeout: int = Field(default=30)
    startup_connect_timeout: int = Field(default=90)
    completeness_floor: float = Field(default=0.5, ge=0.0, le=1.0)
    n_batches_per_round: int = Field(default=2000)
    mix_std: float = Field(default=0.001)
    mix_shuffle: bool = Field(default=True)
    nr_cover_bytes: int = Field(default=100)
    pause_training: bool = Field(default=False)
    cache_covers: bool = Field(default=True)
    max_cover_cache: int = Field(default=100)
    sphinx_body_len: int = Field(default=10240, ge=1024, le=32768)
    moq_enabled: bool = Field(
        default=False,
        description="Enable Media over QUIC (MoQ) transport with hierarchical namespace prefixes",
    )

    @model_validator(mode="after")
    def validate_topology_constraints(self):
        topology = self.topology_type
        node_count = self.n_nodes
        if topology in ("circulant", "ring_lattice"):
            if self.graph_degree % 2 != 0:
                raise ValueError(f"{topology} requires even graph_degree")
            if self.graph_degree >= node_count:
                raise ValueError(f"{topology} requires graph_degree < n_nodes")
        elif topology == "hypercube":
            if node_count < 4 or (node_count & (node_count - 1)) != 0:
                raise ValueError("Hypercube requires n_nodes to be a power of 2 and >= 4")
        return self

    @model_validator(mode="after")
    def validate_byzantine_constraints(self):
        if self.attack_type == "none" and self.n_byzantine > 0:
            raise ValueError("n_byzantine must be 0 when attack_type is 'none'")
        if self.attack_type != "none" and self.n_byzantine == 0:
            raise ValueError("n_byzantine must be > 0 when attack_type is set")
        if self.n_byzantine >= self.n_nodes:
            raise ValueError("n_byzantine must be less than n_nodes")

        special_role_count = self.n_join_late + self.n_exit_early + self.n_byzantine
        if special_role_count > self.n_nodes:
            raise ValueError(
                f"n_join_late + n_exit_early + n_byzantine ({special_role_count}) exceeds n_nodes ({self.n_nodes})"
            )
        return self


class FullNodeConfig(ExperimentConfig):
    node_id: int = Field(default=0, ge=0)
    neighbors: list[int] = Field(default_factory=list, description="Node's direct neighbors")
    topology: dict[int, list[int]] = Field(default_factory=dict, description="Full network topology adjacency map")
    join_schedule: dict[int, int] = Field(default_factory=dict, description="Node join schedule: {node_id: round}")
    exit_schedule: dict[int, int] = Field(default_factory=dict, description="Node exit schedule: {node_id: round}")
    peer_endpoints: dict[int, tuple[str, int]] = Field(
        default_factory=dict, description="{node_id: (host, port)} for every peer in the run"
    )
    controller_url: str = Field(default="http://127.0.0.1:8000")

    def to_env_dict(self) -> dict:
        return {
            "MODEL_NAME": self.model_name,
            "DATASET": self.dataset,
            "NODE_ID": str(self.node_id),
            "N_NODES": str(self.n_nodes),
            "N_ROUNDS": str(self.n_rounds),
            "BATCH_SIZE": str(self.batch_size),
            "TORCH_THREADS": str(self.torch_threads),
            "OMP_NUM_THREADS": str(self.torch_threads),
            "MKL_NUM_THREADS": str(self.torch_threads),
            "DIRICHLET_ALPHA": str(self.dirichlet_alpha),
            "MIX_ENABLED": str(self.mix_enabled).lower(),
            "MIX_MU": str(self.mix_mu),
            "MAX_HOPS": str(self.max_hops),
            "PORT": str(self.port),
            "CONTROLLER_URL": self.controller_url,
            "RESEND_TIME": str(self.resend_time),
            "PUSH_METRIC_INTERVAL": str(self.push_metric_interval),
            "STALL_TIMEOUT": str(self.stall_timeout),
            "STARTUP_CONNECT_TIMEOUT": str(self.startup_connect_timeout),
            "COMPLETENESS_FLOOR": str(self.completeness_floor),
            "N_BATCHES_PER_ROUND": str(self.n_batches_per_round),
            "MIX_STD": str(self.mix_std),
            "MIX_SHUFFLE": str(self.mix_shuffle).lower(),
            "MIX_OUTBOX_SIZE": str(self.mix_outbox_size),
            "NR_COVER_BYTES": str(self.nr_cover_bytes),
            "PAUSE_TRAINING": str(self.pause_training).lower(),
            "CACHE_COVERS": str(self.cache_covers).lower(),
            "MAX_COVER_CACHE": str(self.max_cover_cache),
            "JOIN_SCHEDULE": json.dumps({str(k): v for k, v in self.join_schedule.items()})
            if self.join_schedule
            else "",
            "EXIT_SCHEDULE": json.dumps({str(k): v for k, v in self.exit_schedule.items()})
            if self.exit_schedule
            else "",
            "NEIGHBORS": ",".join(map(str, self.neighbors)) if self.neighbors else "",
            "TOPOLOGY": json.dumps({str(k): v for k, v in self.topology.items()}) if self.topology else "",
            "PEER_ENDPOINTS": json.dumps({str(k): [v[0], v[1]] for k, v in self.peer_endpoints.items()})
            if self.peer_endpoints
            else "",
            "QUANTIZATION_BITS": str(self.quantization_bits),
            "SPHINX_BODY_LEN": str(self.sphinx_body_len),
            "AGGREGATION_ALGORITHM": self.aggregation_algorithm,
            "KRUM_BYZANTINE_FRACTION": str(self.krum_byzantine_fraction),
            "ATTACK_TYPE": self.attack_type,
            "N_BYZANTINE": str(self.n_byzantine),
            "ATTACK_NOISE_SIGMA": str(self.attack_noise_sigma),
            "PARTIAL_UPDATE_RATIO": str(self.partial_update_ratio),
            "MOQ_ENABLED": str(self.moq_enabled).lower(),
        }
