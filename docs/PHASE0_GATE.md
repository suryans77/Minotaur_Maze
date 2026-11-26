# Phase 0 gate review

Status of every Phase 0 item in [`BUILD_PLAN.md`](BUILD_PLAN.md), audited on
**2026-11-26** against commit `c3d4b9d`, the GitHub API, and the demo
machine (WSL2 Ubuntu on a 15.3 GB Windows laptop).

**Phase 0 is not complete.** Two exit-gate items fail outright: memory, and
the team PR check. Four more still need a live check. Re-run the commands
below and tick items only when they pass.

Legend: **Verified** = checked during the audit, with evidence.
**Manual** = in place, but needs a live check a person must run.
**Open** = not done, or failing.

## Exit gate

| # | Gate item | Status | Evidence on 2026-11-26 |
|---|---|---|---|
| G1 | A push makes Jenkins start a job within 10 s | Manual | GitHub delivered every push to Jenkins with HTTP 200 (0.8–2.3 s). That the *job started* within 10 s has not been timed |
| G2 | After a reboot, a push still triggers Jenkins: `ngrok.service` returns by itself, URL unchanged | Manual | WSL booted 13:04:55. `ngrok.service` (enabled) was up at 13:06:18 without manual action, with the same static URL. Pushes at 13:21 and 15:09 were delivered with 200. Not yet confirmed: a full Windows reboot, and the job actually starting |
| G3 | `systemctl kill --signal=KILL ngrok` → tunnel back within 10 s | Manual | Unit has `Restart=always`, `RestartSec=5s`. The kill test has not been run since boot (`NRestarts=0`) |
| G4 | GitHub *Recent Deliveries* shows 200 from Jenkins | **Verified** | Hook active, push events, JSON, path `/github-webhook/`. Last 4 deliveries (ping + 3 pushes) all 200 |
| G5 | `kubectl get nodes` Ready; `kubectl top nodes` returns numbers | **Verified** | Node `minikube` Ready, v1.37.0. `kubectl top nodes` returned 210m CPU / 1065Mi. Profile: 6144 MB, 4 CPUs, docker driver. Addons metrics-server and ingress enabled; ingress controller Running |
| G6 | Kibana opens with Minikube and Jenkins running; `free -h` shows no swapping | **Open** | Kibana `/api/status` returned 200 with Minikube and Jenkins up. But WSL has only **7.4 GiB RAM and no swap**, and **Elasticsearch has been OOM-killed 14 times** by its own 1.5 GiB container limit. See [Blocker 1](#blocker-1-memory) |
| G7 | All three people can clone, branch and open a PR | **Open** | Collaborators: `suryans77` (admin), `gathik-jindal` (write). **`Aarpeet`'s invitation is still pending.** No branch other than `main` has been pushed; no PR has ever been opened |

## Phase 0 tasks

### Dev A: game

| Task | Status | Evidence |
|---|---|---|
| Design the maze: ≥ 25×25, 3 exits, loops, valid start cells | **Verified** | `levels/maze.json`: 51×51 (25×25 rooms), 3 exits, braid ratio 15.10 %, 1,199 start cells. 121 tests pass |
| Maze file format | **Verified** | Documented in `levels/README.md`; tunable settings in `config/game.yaml` |
| `game/` FastAPI app with WebSocket endpoint and pytest | **Verified** | `/health`, `/ws`; tests cover connect, disconnect and abrupt drop on a real uvicorn |

### Dev B: pipeline and infrastructure

| Task | Status | Evidence |
|---|---|---|
| Docker | **Verified** | Docker Engine 29.9.1 (Docker Desktop WSL integration); socket group `docker` |
| Minikube `--memory=6144 --cpus=4`, metrics-server, ingress | **Verified** | See G5 |
| kubectl, Ansible | **Verified** | kubectl configured for `suryans`; `ansible [core 2.20.1]` installed |
| Jenkins with Docker socket and Minikube kubeconfig | Manual | Jenkins runs as a **host service** (Build Plan fallback, not in Docker): active, enabled, HTTP 200 on :8080, ~728 MiB RSS. User `jenkins` is in group `docker`. Its kubeconfig could not be read without `sudo`: **Jenkins → Minikube is unverified** |
| ngrok as `ngrok.service`, enabled, restart on failure, static domain | **Verified** (with deviations) | Active, enabled, tunnel to `localhost:8080`. Deviations from SRS Appendix C: `User=suryans` rather than a dedicated `ngrok` user; `Restart=always` (stricter than `on-failure`); `StartLimitIntervalSec=10s` rather than `0` (harmless with `RestartSec=5`). The unit was installed by hand; installing it through the Ansible `jenkins` role is Phase 1 work |
| GitHub webhook to `https://<dev-domain>/github-webhook/` | **Verified** | See G4 |
| Create the Docker Hub repos | **Open** | Not created or verified. Required repositories and steps: [`DOCKER_HUB.md`](DOCKER_HUB.md) |

### Dev C: repository and ELK

| Task | Status | Evidence |
|---|---|---|
| GitHub repo with the SRS folder structure | Partial | Present: `docs/`, `game/`, `levels/`, `config/`, `elk/`. Other Appendix A folders are created by the phase that needs them ([`CONTRIBUTING.md`](../CONTRIBUTING.md#where-things-go)) |
| Branch protection | **Open** | Verified **not enabled** (API: `protected: false`, no rulesets). Steps: [`GITHUB_SETUP.md`](GITHUB_SETUP.md) |
| PR template | Added, not yet on `main` | `.github/pull_request_template.md`. GitHub uses it once merged |
| `docker-compose.elk.yml` with §7.1 heaps and FR-D-06 security | **Verified** | ES `-Xms1g -Xmx1g`, `xpack.security.enabled=true`, `xpack.security.http.ssl.enabled=false`; Logstash `-Xms512m -Xmx512m`. ES answers 401 without credentials |
| Kibana opens | **Verified** | `/api/status` → 200. But see G6 |

### Repository hygiene

| Check | Status | Evidence |
|---|---|---|
| No secrets in tracked files or history | **Verified** | Pattern scan of all history found nothing. `.env` was never committed; only `.env.example` is tracked |
| `.gitignore` covers env files, Python caches, venvs, editor/OS files, vault password files | **Verified** | Root `.gitignore`; `git status --ignored` shows `.env`, `.venv/` and caches ignored |
| SRS in `docs/` and consistent with the code | **Verified** | `docs/SRS.md` FR-G-02 now states the distinct-route and endpoint rules. The two **PDFs at the repo root still carry the old FR-G-02 wording**; `docs/SRS.md` is the reference |
| Root `README.md` | Noted | UTF-16 encoded; contains only a title and an `export ANSIBLE_CONFIG=…` line. Left untouched |

## Blocker 1: memory

**What is happening.** Elasticsearch runs with a 1 GB heap inside a 1.5
GiB container limit (SRS §7.1). The JVM's off-heap memory pushes it past
the limit. The kernel log shows `Memory cgroup out of memory: Killed process
… (java)` for that container, and `docker inspect` reports 14 restarts.
Separately, WSL sees only 7.4 GiB of the laptop's 15.3 GB, because
`%UserProfile%\.wslconfig` is empty. The SRS budget assumes about 13 GB for
the cluster, ELK and Jenkins. The containers' limits alone (Minikube 6 GiB
+ ELK 3.3 GiB) exceed 7.4 GiB, and there is no swap.

**Fix (owners: Dev B for WSL, Dev C for ELK; not applied by this review):**

1. Give WSL the memory the SRS budget assumes. In Windows, write
   `C:\Users\<you>\.wslconfig`:
   ```ini
   [wsl2]
   memory=12GB
   swap=4GB
   ```
   then in PowerShell run `wsl --shutdown`, and reopen Ubuntu.
   `free -h` should show about 12 GiB total and 4 GiB swap.
2. Stop the Elasticsearch OOM loop. Either lower its heap to 768 MB, the
   Build Plan's documented fallback (`ES_JAVA_OPTS=-Xms768m -Xmx768m`), or
   raise its container limit to 2 GiB and update SRS §7.1 to match.
3. Re-check (G6 commands below). The restart count must stop increasing,
   and `vmstat` must show `si`/`so` at 0 under load.

## Commands for the remaining checks

Run on the demo machine, in Ubuntu (WSL) unless stated.

**G1: push to job start within 10 s.** Run this before branch protection
is on, or via a PR merge afterwards. `<JOB>` is the Jenkins job name;
`JENKINS_USER` and `JENKINS_API_TOKEN` are your Jenkins login and an API
token from *Jenkins → your user → Security*.

```sh
git commit --allow-empty -m "chore: webhook timing check" && git push
HOOK=$(gh api repos/suryans77/Minotaur_Maze/hooks --jq '.[0].id')
gh api "repos/suryans77/Minotaur_Maze/hooks/$HOOK/deliveries?per_page=1" --jq '.[0] | "\(.delivered_at) \(.status_code)"'
curl -s -u "$JENKINS_USER:$JENKINS_API_TOKEN" \
  "http://localhost:8080/job/<JOB>/lastBuild/api/json?tree=number,timestamp" \
  | python3 -c 'import json,sys,datetime as d; j=json.load(sys.stdin); print(j["number"], d.datetime.fromtimestamp(j["timestamp"]/1000, d.timezone.utc).isoformat())'
# Pass: build start time minus delivery time is under 10 s.
```

**G2: after a reboot.** Restart Windows, or at least run `wsl --shutdown`
in PowerShell. Then open Ubuntu. WSL services start only once the distro
starts, so on demo day open Ubuntu first.

```sh
systemctl is-active ngrok jenkins                       # active, active
curl -s localhost:4040/api/tunnels | python3 -c 'import json,sys; print([t["public_url"] for t in json.load(sys.stdin)["tunnels"]])'
# Pass: same https://<dev-domain> as the webhook URL; then repeat G1.
```

**G3: kill ngrok.**

```sh
sudo systemctl kill --signal=KILL ngrok
sleep 10
systemctl show ngrok -p ActiveState -p NRestarts        # ActiveState=active, NRestarts=1
curl -s localhost:4040/api/tunnels | python3 -c 'import json,sys; print([t["public_url"] for t in json.load(sys.stdin)["tunnels"]])'
# Pass: the same https://<dev-domain> URL is listed again within 10 s of the kill.
```

**Jenkins → Docker and Minikube (also after every `minikube start`).**

```sh
sudo -u jenkins docker ps --format '{{.Names}}' | head -3
sudo -u jenkins kubectl get nodes                       # minikube   Ready
```

With the docker driver, Minikube publishes its API server on a
**different random localhost port after every restart** (today
`127.0.0.1:60111`). A kubeconfig copied into Jenkins therefore goes stale.
If the second command fails, refresh it:

```sh
kubectl config view --flatten --minify --context minikube > /tmp/jenkins-kubeconfig
sudo install -D -o jenkins -g jenkins -m 600 /tmp/jenkins-kubeconfig /var/lib/jenkins/.kube/config
rm /tmp/jenkins-kubeconfig
```

**G5: node and metrics** (verified, re-run after reboots).

```sh
minikube status && kubectl get nodes && kubectl top nodes
minikube addons list | grep -E 'metrics-server|ingress '
```

**G6: Kibana and memory, with everything running.**

```sh
systemctl is-active jenkins && kubectl get nodes --no-headers
curl -s -o /dev/null -w 'kibana %{http_code}\n' localhost:5601/api/status   # 200
free -h                                                    # swap "used" stays ~0
vmstat 5 6                                                 # si and so columns 0
docker inspect minotaur-elasticsearch --format 'restarts={{.RestartCount}} oom={{.State.OOMKilled}}'
sudo dmesg | grep -c 'Killed process'                      # must not grow between runs
docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}'
```

**G7: team clone, branch and PR.** See
[`GITHUB_SETUP.md` §2](GITHUB_SETUP.md#2-team-access).

## Checklist

Tick only after the check passes.

- [ ] G1 Push → Jenkins job starts within 10 s (timed)
- [ ] G2 After a Windows reboot, ngrok is back on the same URL and a push triggers a job
- [ ] G3 `systemctl kill --signal=KILL ngrok` → tunnel back within 10 s
- [x] G4 Recent Deliveries show 200 (verified 2026-11-26)
- [x] G5 Node Ready, `kubectl top nodes` works (verified 2026-11-26)
- [ ] G6 Kibana opens with everything running and no swapping; Elasticsearch restart count stable
- [ ] G7 All three members cloned, branched and opened a PR
- [ ] Jenkins user can run `docker ps` and `kubectl get nodes`
- [ ] Branch protection on `main` enabled and verified
- [ ] PR template merged to `main`
- [ ] Docker Hub repositories `game`, `minotaur`, `frontend` exist under the agreed namespace
- [ ] Jenkins holds the Docker Hub token as a credential
