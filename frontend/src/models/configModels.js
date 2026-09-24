// keys are API field names and must match the backend exactly, so don't rename them
export const CONFIG_SCHEMA = {
  model_name: {
    default: 'lenet5',
    type: 'select',
    options: ['lenet5', 'squeezenet', 'mobilenetv2'],
    label: 'Model',
    optionLabels: {
      lenet5: 'LeNet-5 (~62K params)',
      squeezenet: 'SqueezeNet (~727K params)',
      mobilenetv2: 'MobileNetV2 (~2.2M params)',
    },
    section: 'learning',
  },
  dataset: {
    default: 'mnist',
    type: 'select',
    options: ['mnist', 'cifar10', 'fashion_mnist'],
    label: 'Dataset',
    optionLabels: {
      mnist: 'MNIST (handwritten digits)',
      cifar10: 'CIFAR-10 (color images)',
      fashion_mnist: 'Fashion-MNIST (clothing items)',
    },
    section: 'learning',
  },
  n_nodes: {
    default: 10,
    min: 1,
    max: 100,
    type: 'int',
    label: 'Number of Nodes',
    section: 'network',
  },
  topology_type: {
    default: 'full_mesh',
    type: 'select',
    options: ['full_mesh', 'circulant', 'ring_lattice', 'hypercube'],
    label: 'Topology',
    optionLabels: {
      full_mesh: 'Full Mesh (all-to-all)',
      circulant: 'Circulant (even degree, optimized)',
      ring_lattice: 'Ring Lattice (consecutive neighbors)',
      hypercube: 'Hypercube (log-degree, power of 2)',
    },
    section: 'network',
  },
  graph_degree: {
    default: 4,
    min: 2,
    max: 10,
    type: 'int',
    label: 'Graph Degree',
    section: 'network',
    visibleWhen: (cfg) => cfg.topology_type === 'circulant' || cfg.topology_type === 'ring_lattice',
  },
  n_rounds: {
    default: 10,
    min: 1,
    max: 100,
    type: 'int',
    label: 'Training Rounds',
    section: 'learning',
  },
  batch_size: {
    default: 64,
    min: 16,
    max: 256,
    type: 'int',
    label: 'Batch Size',
    section: 'learning',
  },
  torch_threads: {
    default: 1,
    min: 1,
    max: 64,
    type: 'int',
    label: 'Torch Threads',
    section: 'learning',
  },
  dirichlet_alpha: {
    default: 10.0,
    min: 0.1,
    max: 100.0,
    type: 'float',
    label: 'Dirichlet Alpha',
    section: 'learning',
  },
  mix_enabled: {
    default: true,
    type: 'bool',
    label: 'Enable Mixnet',
    section: 'mixnet',
  },
  mix_mu: {
    default: 0.1,
    min: 0.001,
    max: 1.0,
    type: 'float',
    label: 'Mix Interval (s)',
    section: 'mixnet',
  },
  max_hops: {
    default: 2,
    min: 1,
    max: 5,
    type: 'int',
    label: 'Max Hops',
    section: 'mixnet',
  },
  mix_outbox_size: {
    default: 10,
    min: 1,
    max: 200,
    type: 'int',
    label: 'Outbox Size',
    section: 'mixnet',
  },
  aggregation_algorithm: {
    default: 'fedavg',
    type: 'select',
    options: ['fedavg', 'krum'],
    label: 'Aggregation',
    optionLabels: {
      fedavg: 'FedAvg',
      krum: 'Krum (Byzantine-robust)',
    },
    section: 'learning',
  },
  quantization_bits: {
    default: 8,
    type: 'select',
    options: [8, 32],
    label: 'Quantization',
    optionLabels: {
      8: '8-bit (~4x smaller)',
      32: '32-bit (full precision)',
    },
    section: 'learning',
  },
  attack_type: {
    default: 'none',
    type: 'select',
    options: ['none', 'label_flip', 'gaussian_noise'],
    label: 'Attack Type',
    optionLabels: {
      none: 'None',
      label_flip: 'Label Flipping',
      gaussian_noise: 'Gaussian Noise',
    },
    section: 'learning',
  },
  n_byzantine: {
    default: 0,
    min: 0,
    max: 99,
    type: 'int',
    label: 'Byzantine Nodes',
    section: 'learning',
    visibleWhen: (cfg) => cfg.attack_type !== 'none',
  },
  partial_update_ratio: {
    default: 1.0,
    min: 0.01,
    max: 1.0,
    type: 'float',
    label: 'Partial Update Ratio',
    section: 'mixnet',
  },
  n_join_late: {
    default: 0,
    min: 0,
    max: 39,
    type: 'int',
    label: 'Late-Joining Nodes',
    section: 'network',
  },
  n_exit_early: {
    default: 0,
    min: 0,
    max: 39,
    type: 'int',
    label: 'Early-Exiting Nodes',
    section: 'network',
  },
  moq_enabled: {
    default: false,
    type: 'bool',
    label: 'Media over QUIC (MoQ)',
    section: 'network',
  },
};

export function getDefaultConfig(initialOverrides = {}) {
  const config = {};
  Object.entries(CONFIG_SCHEMA).forEach(([key, schema]) => {
    config[key] = schema.default;
  });
  return { ...config, ...initialOverrides };
}

function validateConfigValue(key, value) {
  const schema = CONFIG_SCHEMA[key];
  if (!schema) {
    return { valid: false, error: 'Unknown config key' };
  }

  if (schema.type === 'bool') {
    return { valid: typeof value === 'boolean' };
  }

  if (schema.type === 'select') {
    return { valid: schema.options.includes(value) };
  }

  if (schema.type === 'int' || schema.type === 'float') {
    const numericValue = Number(value);

    if (isNaN(numericValue)) {
      return { valid: false, error: 'Must be a number' };
    }
    if (schema.min !== undefined && numericValue < schema.min) {
      return { valid: false, error: `Minimum value is ${schema.min}` };
    }
    if (schema.max !== undefined && numericValue > schema.max) {
      return { valid: false, error: `Maximum value is ${schema.max}` };
    }
    if (schema.type === 'int' && !Number.isInteger(numericValue)) {
      return { valid: false, error: 'Must be an integer' };
    }

    return { valid: true };
  }

  return { valid: true };
}

export function validateConfig(config) {
  const errors = {};
  let valid = true;

  Object.keys(CONFIG_SCHEMA).forEach((key) => {
    const value = config[key] !== undefined ? config[key] : CONFIG_SCHEMA[key].default;
    const result = validateConfigValue(key, value);
    if (!result.valid) {
      valid = false;
      errors[key] = result.error;
    }
  });

  const topology = config.topology_type;
  const nNodes = Number(config.n_nodes);

  if (topology === 'circulant' || topology === 'ring_lattice') {
    const degree = Number(config.graph_degree);
    if (degree % 2 !== 0) {
      valid = false;
      errors.graph_degree = 'Must be even';
    }
    if (degree >= nNodes) {
      valid = false;
      errors.graph_degree = 'Must be less than number of nodes';
    }
  }

  if (topology === 'hypercube') {
    if (nNodes < 4 || (nNodes & (nNodes - 1)) !== 0) {
      valid = false;
      errors.n_nodes = 'Hypercube requires a power of 2 (4, 8, 16, 32)';
    }
  }

  const nByzantine = Number(config.n_byzantine) || 0;
  const nJoinLate = Number(config.n_join_late) || 0;
  const nExitEarly = Number(config.n_exit_early) || 0;
  const attackType = config.attack_type;

  if (nJoinLate + nExitEarly + nByzantine > nNodes) {
    valid = false;
    errors.n_byzantine = 'join + exit + byzantine exceeds total nodes';
  }

  if (nByzantine > 0 && attackType === 'none') {
    valid = false;
    errors.attack_type = 'Select an attack type when Byzantine nodes > 0';
  }

  if (nByzantine === 0 && attackType !== 'none') {
    valid = false;
    errors.n_byzantine = 'Set Byzantine nodes > 0 for the selected attack';
  }

  return { valid, errors };
}
