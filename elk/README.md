# ELK stack

Elasticsearch, Logstash and Kibana 8.19.26 for Minotaur Maze, run with Docker Compose
outside the Kubernetes cluster (SRS FR-D-06, §2.3, §8). Run every command below from
the repository root.

| Service | Address | Memory limit (SRS §7.1) |
|---|---|---|
| Elasticsearch | http://localhost:9200 | 1.5 GB (1 GB heap) |
| Kibana | http://localhost:5601 | 1.0 GB |
| Logstash Beats input | 127.0.0.1:5044 | 0.8 GB (512 MB heap, 2 workers) |
| `setup` (one-shot) | none | 128 MB, exits when done |

Logstash routes events into three daily index families:

| Index | Events |
|---|---|
| `minotaur-game-*` | `game_start`, `step`, `game_end` |
| `minotaur-ai-*` | `minotaur_decision`, `prediction_outcome`, `fallback` |
| `minotaur-pipeline-*` | `model_trained`, `model_deployed`, `app_deployed` |

`error` events and unknown event types go to the index of the service that emitted
them (`minotaur` → ai; `trainer`/`pipeline` → pipeline; anything else → game).
Unknown types are tagged `_unknown_event_type`. Lines that are not JSON objects,
or that lack `ts`, `event` or `service`, are dropped.

## 1. Configure the environment

```bash
cp .env.example .env
# Fill in every value. Passwords: 16+ chars of [A-Za-z0-9_-].
openssl rand -hex 24   # for ELASTIC_PASSWORD, KIBANA_SYSTEM_PASSWORD, LOGSTASH_INTERNAL_PASSWORD
openssl rand -hex 32   # for KIBANA_ENCRYPTION_KEY, and again for KIBANA_SECURITY_ENCRYPTION_KEY
chmod 600 .env
```

`.env` is git-ignored. Compose refuses to start if any required value is empty.
Generate every value locally on this machine; never paste real values into
`.env.example`, an issue, or a commit.

Kibana uses two separate, persistent keys. Keep both stable once set:

| Variable | Kibana setting | If it changes |
|---|---|---|
| `KIBANA_ENCRYPTION_KEY` | `xpack.encryptedSavedObjects.encryptionKey` | Existing alerting rules and other encrypted saved objects become unreadable |
| `KIBANA_SECURITY_ENCRYPTION_KEY` | `xpack.security.encryptionKey` | Every active Kibana session is logged out |

`ELASTIC_PASSWORD` is applied only when the Elasticsearch data volume is first
created. To change it later, use the Elasticsearch change-password API. Editing
`.env` alone does not change it.

Recommended on the host, so Elasticsearch can map its index files:

```bash
sudo sysctl -w vm.max_map_count=262144
```

## 2. Start

```bash
docker compose -f docker-compose.elk.yml up -d
```

Startup order is enforced by health checks: Elasticsearch becomes healthy, then
`setup` sets the `kibana_system` password and creates the `logstash_internal`
writer, then Logstash and Kibana start. Expect 1–3 minutes on first start.

## 3. Check health

```bash
docker compose -f docker-compose.elk.yml ps
```

`elasticsearch`, `logstash` and `kibana` should show `(healthy)`, and `setup`
should show `Exited (0)`. If something is not healthy:

```bash
docker compose -f docker-compose.elk.yml logs setup
docker compose -f docker-compose.elk.yml logs -f elasticsearch logstash kibana

# Elasticsearch cluster health. Prompts for the elastic password so it stays
# out of shell history. Yellow is normal on a single node.
curl -u elastic 'http://localhost:9200/_cluster/health?pretty'

# Logstash pipeline health (the API is not published outside the container)
docker compose -f docker-compose.elk.yml exec logstash \
  curl -s 'http://localhost:9600/_health_report?pretty'

# Memory use against the SRS §7.1 budget
docker stats --no-stream minotaur-elasticsearch minotaur-logstash minotaur-kibana
```

## 4. Open Kibana

Open http://localhost:5601 and log in as user `elastic` with `ELASTIC_PASSWORD`
from `.env`. Events show up in Discover once you create a data view for
`minotaur-*`. Dashboards come in a later phase (SRS §8.2).

### Reaching Logstash and Elasticsearch from Minikube

Every ELK port is published on **127.0.0.1 only** (Logstash 5044, Elasticsearch
9200, Kibana 5601). Never change a binding to `0.0.0.0` or to a LAN address: on
Docker Desktop that exposes the port on every Windows network interface, and
the Beats input has no authentication, so anyone who can reach it could inject
events into the training data.

On this host the `docker` CLI in WSL talks to **Docker Desktop's** engine, and
Minikube (docker driver) runs as a container on that same engine. Docker
Desktop forwards a container's connections to `host.docker.internal` (currently
192.168.65.254) to the host, where they reach ports published on 127.0.0.1. So
the candidate addresses for pods are:

| From a pod | Candidate address |
|---|---|
| Filebeat → Logstash | `host.docker.internal:5044` |
| Trainer → Elasticsearch | `http://host.docker.internal:9200` (authenticated) |

> **Unverified from inside Kubernetes.** This path has been tested only from a
> plain container attached to the `minikube` Docker network, not from a pod.
> Pods additionally depend on CoreDNS resolving `host.docker.internal` and on
> the node forwarding pod traffic. Verify it from a real pod before relying on
> it (requires Logstash running):
>
> ```bash
> kubectl run elk-nettest --rm -it --restart=Never --image=busybox:1.36 -- \
>   sh -c 'nslookup host.docker.internal; nc -zv -w 3 host.docker.internal 5044'
> ```
>
> If the name does not resolve inside the pod but the IP connects, address the
> host by IP from Kubernetes instead of by name.

Approaches that do **not** work here:

- Binding a port to the Minikube network gateway (192.168.49.1): Docker Desktop
  rejects it (`ports are not available ... /forwards/expose returned unexpected
  status: 500`).
- `host.minikube.internal`: on this setup it is expected to point at that same
  gateway, where nothing listens (connection refused).
- Attaching ELK containers to the `minikube` Docker network: a container
  started while Minikube is stopped can take the Minikube node's address
  (192.168.49.2) and break `minikube start`.

Because 127.0.0.1 ports are reachable from every container on this Docker
Desktop engine (not from the LAN), any local container could send events to
port 5044. That is accepted for local development.

## 5. Stop (keeps data)

```bash
docker compose -f docker-compose.elk.yml stop     # stop containers, keep them
# or
docker compose -f docker-compose.elk.yml down     # remove containers and network, KEEP the data volume
```

Indexed data stays in the `minotaur-elk-esdata` volume and is available again on
the next `up -d`.

## 6. Remove everything, including data

> **Warning — permanent data loss.** This deletes the Elasticsearch volume:
> every indexed event, the training corpus the model pipeline reads (FR-M-07),
> Kibana saved objects, and the users created by `setup`. It cannot be undone.

```bash
docker compose -f docker-compose.elk.yml down --volumes
```

The next `up -d` starts from an empty cluster and applies `ELASTIC_PASSWORD` from
`.env` again.
