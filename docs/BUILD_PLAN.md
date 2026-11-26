# Minotaur Maze — Build Plan (v2)

Nov 25, 2026 · @suryans

Three people build the reduced-scope Minotaur Maze in seven phases over about 17 working days, each phase ending in a gate that must pass before the next starts. The order puts the riskiest work first: the full mandatory pipeline runs against a placeholder app by day 5, so most of the 20 working-project marks are safe before the game is even built.

Days are relative to day 1, not calendar dates. v1 ran 21 days; the cuts in SRS v2 take roughly four days out without removing a single gate.

## Team and ownership

Each person owns one layer end to end, so work runs in parallel inside every phase and nobody waits on someone else's half-finished code.

| Role | Owns (folders) | SRS requirements | Course requirements | Demo part |
|---|---|---|---|---|
| **Dev A** — game and bots | `game/`, `frontend/`, `levels/`, `simbots/`, `config/game.yaml` | FR-G-01 to FR-G-17, FR-M-06 | CR-08, CR-11 | Live play; pushing a balance change |
| **Dev B** — pipeline and infrastructure | `Jenkinsfile*`, `*/Dockerfile`, `docker-compose*.yml`, `k8s/`, `ansible/` | FR-D-01 to FR-D-24, NFR-03 to NFR-08 | CR-01 to CR-05, CR-07, CR-09, CR-10, CR-13 to CR-16 | Pipeline run, Kubernetes, scaling, zero-downtime deploy, rollback |
| **Dev C** — data and ML | `elk/`, `minotaur/`, `model/`, `features/` | FR-M-01 to FR-M-23, Section 8 of the SRS | CR-06, CR-12, CR-17, CR-18 | Kibana dashboards, model pipeline, the gates, the drift story |

**Shared by everyone:**

- **The demo machine.** One 16 GB laptop runs Minikube, Jenkins and ELK, within the budget in SRS §7.1. Dev B keeps it healthy. Dev A and Dev C develop on their own machines with Docker Compose and merge through GitHub.
- **The integration test.** Whoever breaks the pipeline fixes it before starting anything new.
- **The viva.** Each person must be able to explain the whole system, not only their part. Phase 6 sets aside time for this.

**Two contracts are shared and must not be changed unilaterally:**

| Contract | Between | Note |
|---|---|---|
| The Minotaur API | Dev A and Dev C | The request schema must never carry the active exit (FR-G-04). Adding it, even by accident, invalidates every accuracy number in the project |
| `features/` | Dev C with itself | One module imported by both `model/` and `minotaur/` (FR-M-23). A second copy of the feature code on the serving side is the most likely way to silently lose accuracy |

Change either one only together, and update the SRS in the same PR.

## Phases at a glance

**Phase 1 banks most of the 20 marks on day 5**
*Seven phases, seven gates, about 17 working days*

| Phase | Days | Outcome | Marks | Gate |
|---|---|---|---|---|
| P0 Foundations | days 1 to 2 | every tool installed and talking | | G0 |
| **P1 Walking skeleton** | **days 3 to 5** | **mandatory pipeline runs on a placeholder** | **20 marks** | **G1** |
| P2 Playable game | days 6 to 8 | real game on the cluster, rule-based hunt | | G2 |
| P3 Data + dashboards | days 9 to 10 | 300 bot games stored, 3 dashboards built | | G3 |
| P4 ML and pipeline | days 11 to 13 | exit predictor hunts; model pipeline gates | 5 + 2 marks | G4 |
| P5 Scale and secrets | days 14 to 15 | HPA under load, zero-downtime, Vault | 3 marks | G5 |
| P6 Harden, rehearse | days 16 to 17 | drift story, 2 rehearsals, main frozen | | G6 |

*roadmap · 7 phases, 7 gates, 17 days*

The seven phases run strictly in order, and each ends in a gate review on the demo machine. Phase 1 is highlighted because once its gate passes, the mandatory pipeline — CR-01 to CR-12 — already works end to end against a placeholder, and the bulk of the 20 working-project marks is safe before a single line of game logic ships.

Everything after Phase 1 is adding features to a pipeline that already works, which is a very different problem from building both at once.

## Phases 0–3 — pipeline first, then the game

Each phase ends in an exit gate: a short list of things the whole team can see working on the demo machine. The next phase starts only when every box is ticked. Inside a phase, the three people work in parallel.

### Phase 0 — Foundations (days 1–2)

**Goal:** every tool installed and talking to the others on the demo machine, the repo in place, and everyone agreed on the design.

**Why first:** tool setup is where student DevOps projects lose the most time, and none of it can be generated for you. Doing it on day 1 exposes RAM, permission and network problems while there is still slack.

| Dev A | Dev B | Dev C |
|---|---|---|
| Read SRS §3–4; design the one maze on paper — 25×25 or larger, 3 exits, loops, a set of valid start cells; scaffold `game/` as a FastAPI app with a WebSocket endpoint and pytest; write the maze file format | On the demo machine install Docker, Minikube (`--memory=6144 --cpus=4`, with metrics-server and ingress addons), kubectl, Ansible, and Jenkins in Docker with access to the Docker socket and the Minikube kubeconfig; install ngrok and run `ngrok http 8080` as the systemd service `ngrok.service` (enabled at boot, `Restart=on-failure`, SRS Appendix C) on the account's static dev domain; add the GitHub webhook pointing to `https://<dev-domain>/github-webhook/`; create the Docker Hub repos | Create the GitHub repo with the SRS folder structure, branch protection and a PR template; write `docker-compose.elk.yml` with the heaps and the FR-D-06 Elasticsearch security settings from SRS §7.1; confirm Kibana opens |

**Exit gate:**

- [ ] A push to the repo makes Jenkins start a job within 10 seconds
- [ ] After a reboot of the demo machine, a push still triggers Jenkins: `ngrok.service` comes back on its own and the webhook URL is unchanged
- [ ] `sudo systemctl kill --signal=KILL ngrok` → the tunnel is back within 10 s and `systemctl status ngrok` shows the restart
- [ ] GitHub's webhook *Recent Deliveries* shows a 200 response from Jenkins
- [ ] `kubectl get nodes` shows the node Ready, and `kubectl top nodes` returns numbers
- [ ] Kibana opens with Minikube and Jenkins also running, and `free -h` shows no swapping
- [ ] All three people can clone, branch and open a PR

**Risks:** Jenkins cannot reach Docker or Minikube — fix with socket mounts and a copied kubeconfig. 16 GB is tight — hold to the §7.1 budget rather than improvising.

### Phase 1 — Walking skeleton (days 3–5)

**Goal:** a placeholder page goes through the complete mandatory pipeline: push → Jenkins → tests → Docker Hub → Ansible → Kubernetes → refresh shows the change → its logs appear in Kibana.

**Why here:** this one phase covers CR-01 to CR-12, the bulk of the 20 working-project marks. After it, everything is adding features to a pipeline that already works, instead of fighting the pipeline and the features at once. **This is the phase that is never compressed.**

| Dev A | Dev B | Dev C |
|---|---|---|
| Build the real game rules offline with unit tests: maze loading, movement, walls, line of sight, noise, exits, safe zones, win and loss, random start selection. No graphics yet | Write the app `Jenkinsfile` — checkout, gitleaks, tests, Docker build with build-number tags, push, Ansible deploy, smoke test; Ansible roles `common`, `docker`, `k8s_cluster`, `deploy`; Deployment, Service and Ingress for the placeholder | Filebeat DaemonSet and Logstash pipeline; make the placeholder log JSON events; a first Kibana view of them; set up the empty `minotaur/` service so it can be deployed too |

**Exit gate:**

- [ ] Changing the placeholder's text and pushing updates the page on refresh, with the new build number, with no manual step
- [ ] A deliberately failing test stops the pipeline before Docker Hub
- [ ] Images tagged with the build number appear on Docker Hub
- [ ] The placeholder's log events appear in Kibana within a minute
- [ ] The full pipeline run is timed and completes in under 5 minutes — restructure now if it does not, never in Phase 6

**Risks:** Kubernetes does not redeploy when the tag does not change — always tag with the build number, never `latest`.

### Phase 2 — Playable game (days 6–8)

**Goal:** the real game is playable through the cluster, with a rule-based Minotaur running as its own service, and bots that can play it.

**Why here:** the ML phase needs a working game to generate data, and the scaling phase needs the real two-service split. The rule-based Minotaur built here is kept permanently — as the ablation baseline (FR-M-19) *and* as the production fallback when the model service fails (FR-M-22).

| Dev A | Dev B | Dev C |
|---|---|---|
| Game loop at 10 ticks/s over WebSocket; the canvas page showing the whole maze and the active exit, with the Minotaur visible only in line of sight, plus timer and both version labels; random start cell each game; the 4 sim bots playing headless through the same API, with exit-rusher and backtracker measurably more purposeful than right-turner and random-walker | Dockerfiles and Deployments for `game`, `minotaur`, `frontend`; Ingress routing with session affinity and WebSocket timeouts; Docker Compose for the whole app stack; add the bot integration-test stage to the pipeline; bake `config/game.yaml` into the game image | Rule-based Minotaur service — A* chase on sight, patrol, safe-zone rule, anti-camping; the full event schema from SRS Appendix B logged by `game` and `minotaur` |

**Exit gate:**

- [ ] Two classmates can play the level through the Ingress on the cluster
- [ ] The pipeline integration test runs 4 bots to the end of a game on every push
- [ ] Every event type in SRS Appendix B arrives in Elasticsearch
- [ ] The level-solvability test passes from every valid start cell
- [ ] The four bots have visibly different catch rates against the rule-based Minotaur

**Risks:** WebSockets drop through the Ingress — add the timeout and affinity annotations. The game feels bad — keep tuning values in `config/game.yaml`, never in code.

### Phase 3 — Data and dashboards (days 9–10)

**Goal:** a cold-start training set in Elasticsearch, and the Gameplay, Platform and Delivery dashboards built.

**Why here:** the model in Phase 4 trains on this data, so it must exist first. Building dashboards now also gives every later phase a way to see whether its changes work.

| Dev A | Dev B | Dev C |
|---|---|---|
| A headless bot runner that plays fast with sped-up ticks; run ~300 games from the purposeful bots and a separate set from the aimless ones; prepare one visible theme change for later demo pushes | Index lifecycle policy; one index per event family; export Kibana saved objects into `elk/kibana/` and import them with an `elk` Ansible role | The Gameplay dashboard including the catch heatmap, the Platform dashboard, the Delivery dashboard; sanity-check that the bot data looks like play and not like noise |

**Exit gate:**

- [ ] At least 300 purposeful bot games stored, tagged `source: bot` with `bot_style`
- [ ] Aimless-bot games stored and clearly separable by query, so they can be excluded from training
- [ ] Three dashboards load from saved objects in Git
- [ ] The catch heatmap shows a visible pattern rather than uniform noise

**Risks:** the heatmap is noisy — check that the maze is fixed and only the start cell is randomised. Bulk load strains Elasticsearch — send games in batches.

## Phases 4–6 — ML, scale and rehearsal

### Phase 4 — ML Minotaur and model pipeline (days 11–13)

**Goal:** the Minotaur hunts using the exit predictor, and a second Jenkins pipeline trains, gates, versions and deploys models.

**Why here:** it depends on the game (Phase 2), the data (Phase 3) and a working deploy path (Phase 1). It is the domain work worth 5 marks, so it gets three full days even after the cuts.

| Dev A | Dev B | Dev C |
|---|---|---|
| `source: human` / `bot` tagging; run the first classmate playtest; build the fun-gate harness and the settings sweep over 2–3 combinations, and lock the settings minimising `abs(catch_rate − 50)` | `Jenkinsfile.model` — fetch data, train, three gates, build `minotaur:model-<build>`, deploy, log `model_deployed`; the scheduled run; the rollback command; the conditional config fun check in the app pipeline (FR-D-23) | `features/` as a shared module; the LightGBM exit predictor; interception logic wired into hunting; the "nearest exit" baseline; the ablation against the rule-based Minotaur; the quality, fun and latency gates; model metadata; the Minotaur model dashboard |

**Exit gate:**

- [ ] A push under `model/` deploys a new model whose version shows in the game UI and in Kibana
- [ ] At least one model build has been blocked by a gate, with the measured number visible in Jenkins
- [ ] Catch rate against the purposeful bots sits between 40% and 60%
- [ ] The exit predictor beats "nearest exit" at 50% of game time, and beats the 33% random floor throughout
- [ ] The ML Minotaur catches more often than the rule-based one at identical settings
- [ ] Killing the minotaur service mid-game triggers the rule-based fallback with no visible break

**Risks:** the model is *too* accurate and catch rate exceeds 60% — rerun the sweep with lower Minotaur speed or sight range; never weaken the model. Accuracy is mysteriously poor — check that aimless bots were excluded from training, and that `features/` is imported rather than reimplemented on the serving side.

### Phase 5 — Scale, zero downtime and secrets (days 14–15)

**Goal:** the advanced-feature marks — HPA proven under load, deploys that drop no games, and secrets handled through Ansible Vault.

**Why here:** HPA and zero-downtime only mean something once the real services and real load exist. They are also self-contained, so two days is enough when the base is solid.

| Dev A | Dev B | Dev C |
|---|---|---|
| The 40-game load-test script using the bot runner; a curl loop plus 10 bot games to run during deploys | Resource requests and limits on both Deployments; HPA on `minotaur` at 35% CPU; rolling-update settings, readiness probes, `preStop` drain and the 60 s grace period; Ansible Vault file, `secrets` role, Jenkins credentials; Trivy stage in report-only mode | The requests-per-pod and latency panels under load; the three Kibana alert rules writing to the alerts index; verify the model dashboard during scaling |

**Exit gate:**

- [ ] Under load, `minotaur` scales to at least 6 pods and p95 latency returns under 20 ms
- [ ] Requests spread across pods within ±20% of the mean
- [ ] A deploy during 10 running bot games drops zero games and zero requests
- [ ] `kubectl rollout undo` restores the previous model in one command
- [ ] gitleaks finds no plaintext secret; `ansible-vault view` shows the encrypted file
- [ ] Ansible runs as seven roles from a short `site.yml`

**Risks:** HPA shows `<unknown>` targets — metrics-server is missing, or resource requests are not set. The laptop chokes — lower the concurrent-game count and report the number you actually achieved.

### Phase 6 — Harden and rehearse (days 16–17)

**Goal:** a reliable 10-minute demo, a retrained model that shows the drift story, and three people who can each explain the whole system.

**Why last:** nothing new is built here, only fixed, practised and understood.

| Dev A | Dev B | Dev C |
|---|---|---|
| A second classmate playtest; final balance pass; the README, including the paragraph justifying Ansible Vault under the guidelines' equivalent-tools clause | A full rebuild from a clean machine state with `site.yml` to prove it works; build notifications; a screenshot of every pipeline stage as backup | Retrain on a held-back bot style to produce the drift story — accuracy falling, then recovering; final dashboard polish; the innovation and MLOps talking points |
| **Everyone** | A cross-explain session where each person walks through the other two layers; then two full dress rehearsals of the SRS §10.3 demo script | |

**Exit gate:**

- [ ] Every row of the SRS traceability matrix has been shown live at least once
- [ ] Two full rehearsals have run end to end without a manual fix
- [ ] Each person has explained the full architecture without notes
- [ ] A 3-minute recorded demo video exists, for the README and for interviews

If the move predictor is still wanted, it is built here or not at all. From the start of day 17, nothing new is added and `main` is frozen.

## How to work

A 15-minute check-in each day and a strict `main` branch keep three people from stepping on each other.

**Daily routine**

1. **Check-in, 15 minutes.** What each person finished, what they are doing today, what is blocking. Tick finished gate items in this doc.
2. **Work in branches.** One feature branch per task; open a PR into `main` when its tests pass locally.
3. **Merge carefully.** Every merge triggers the pipeline. If it goes red, the person who merged fixes it before starting anything else.
4. **End of day, push.** Push work in progress to the branch even if unfinished, so nothing lives only on one laptop.

**Commit history is graded.** CR-01 asks for commit history by every member, and evaluators check. All three people commit throughout, in their own names — not one person merging everyone's work at the end.

**Gate reviews.** At the end of each phase, all three meet on the demo machine and run the gate list together. Unticked items become the first tasks of the next day.

### Using Claude Code well

- **Give it the SRS.** Keep it in the repo as `docs/SRS.md` and point Claude Code at it, so file names, requirement IDs, ports and the log schema stay consistent across all three people.
- **One task at a time.** Ask for one requirement or one file with its tests — "implement FR-G-08 line of sight with pytest tests" — not "build the game".
- **Paste the exact error.** For pipeline, Kubernetes and ELK problems, give it the full error text and the relevant config file.
- **Read before you merge.** Each person must understand every file they merge. The viva will ask why it works, and the answer cannot be "it was generated".
- **Keep the contracts fixed.** The Minotaur API and the log schema are shared. Change them only together, and update the SRS in the same PR.

## Risks, fallbacks and the cut order

The plan protects marks in order of value. If something slips, cut from the bottom of this table first, and never from Phase 1.

| Risk | Likely when | Early sign | Fallback | Marks protected |
|---|---|---|---|---|
| Jenkins cannot reach Docker or Minikube | Phase 0 | Builds fail at the Docker or kubectl step | Run Jenkins directly on the host instead of in Docker | 20 (working project) |
| 16 GB is not enough | Phase 1 onward | Machine swaps; pods stuck Pending | Hold to the SRS §7.1 budget; stop Jenkins agents when idle; drop Elasticsearch heap to 768 MB | 20 |
| Game takes longer than planned | Phase 2 | Gate 2 not met by day 8 | Drop the canvas polish to a bare grid render; keep rules, fog of war and the three exits | 20 |
| ML Minotaur not ready | Phase 4 | Gate 4 not met by day 13 | Ship the model with interception disabled — predictions logged and dashboarded but hunting stays rule-based. The MLOps loop still runs end to end and still counts | 5 (domain) |
| Fun gate never passes | Phase 4 | Catch rate stays outside the band after the sweep | Widen the sweep range before touching the model; as a last resort widen the band to 35–65% and say so in the viva | 2 (innovation) |
| HPA will not scale | Phase 5 | Targets show `<unknown>` | Check metrics-server and resource requests; lower the CPU target to 25% | 3 (advanced) |
| Not enough human games for the drift story | Phases 4–6 | Fewer than 30 human games by day 13 | Use the bot-style drift story as the primary — train on exit-rusher, serve backtracker traffic, retrain. It is deterministic and demoable on demand | 5 (domain) |
| Classmates unavailable for the live demo | Phase 6 | No volunteers confirmed by day 15 | Run bots in place of players for steps 2 and 7 of the demo script; the zero-downtime claim is just as valid with bot games | 20, CR-16 |

### What gets cut, in order

If day 16 arrives with work outstanding, cut in this order and stop as soon as you are back on schedule:

1. The move predictor, if anyone started it.
2. The Kibana alert rules — FR-M-16's monitoring panel carries the drift story without them.
3. The theme-change demo push, keeping only the balance-change push for CR-11.
4. Trivy entirely — gitleaks alone covers the security story for CR-13.

Nothing below this line is ever cut: the app pipeline, the three model gates, the Ansible roles, the Vault file, the HPA, or the rolling update. Those are 28 of the 30 marks.
