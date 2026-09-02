# Peer Based Mixing for Decentralized Federated Learning

Peer-based decentralized federated learning (DFL) over a stateless mixnet, with full control via FastAPI and a React
frontend. Each peer trains a local PyTorch model and exchanges updates with its neighbors through a peer-based mixnet over QUIC with mutual TLS. 

## Quickstart

### 1. Clone the repository

```bash
git clone https://github.com/Altishofer/scalable_peer_based_mixing_for_dfl
cd scalable_peer_based_mixing_for_dfl
```

### 2. Build the Docker image for nodes

Install Docker: https://docs.docker.com/engine/install/ubuntu/#install-using-the-repository

Install build dependencies:

```bash
sudo apt install libssl-dev libffi-dev
```

```bash
docker build -t dfl_node ./node
```

*or for debugging purposes*

```bash
docker build -t dfl_node ./node --progress=plain --no-cache
```

### 3. Install Python 3.14

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.14 python3.14-venv python3.14-dev
```

### 4. Create a new venv

```bash
python3.14 -m venv .venv
source .venv/bin/activate
```

### 5. Install Python requirements

```bash
pip install --upgrade pip
pip install -r requirements.txt
pip install -r ./node/requirements.txt
```

### 6. Start the FastAPI backend

```bash
uvicorn manager.app:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 60
```

Backend listens on `http://0.0.0.0:8000` (accessible locally and remotely over LAN). The React frontend and the experiment runners reach it directly over HTTP.

### 7. Install Node.js and set up the React frontend

```bash
sudo apt install npm
npm install --prefix frontend
```

### 8. Start the React frontend

```bash
npm start --prefix frontend
```

Frontend runs at [http://localhost:3001](http://localhost:3001).


## Project Structure

```bash
MixDfl/
├── node/               # Dockerized peer node (Python)
│   ├── learning/       # FL training, aggregation, data partitioning
│   ├── communication/  # Sphinx routing, QUIC transport, mixing
│   ├── metrics/        # per-node metric collection
│   └── utils/          # Config, logging, decorators
├── manager/            # FastAPI backend for orchestration
│   ├── controllers/    # HTTP endpoints
│   ├── services/       # Business logic (nodes, metrics, topology)
│   ├── models/         # Pydantic schemas and config models
│   └── utils/          # Docker and certificate utilities
├── frontend/           # React dashboard
├── experiments/        # Jupyter notebooks for analysis
├── metrics/            # Generated CSV time-series files
└── secrets/            # PKI keys and TLS certs (auto-generated)
```
