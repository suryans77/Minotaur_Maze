# Docker Hub repositories

Which images this project publishes, who builds them, and how they are
tagged. Derived from SRS v2 (§2.4, §5, FR-D-04, FR-D-10, FR-D-15, FR-M-13,
FR-D-24, 6.2 step 8–10, 6.3 step 4) and Build Plan v2.

**Status (2026-11-26):** no Dockerfile exists yet. They arrive in Phase 1
and 2. The Docker Hub repositories below have **not been created or
verified** from this repository. The local Docker login on the demo machine
is the Docker Hub account `suryans77`. Confirm that is the namespace the
team wants before creating anything.

## Repositories to create

`<ns>` is the Docker Hub namespace (account or organisation). Repository
names follow the SRS's `<service>:<build>` convention.

| Repository | Built from | Published by | Tags | Deployed as | Needed by |
|---|---|---|---|---|---|
| `<ns>/game` | `game/Dockerfile`, with `config/game.yaml` and `levels/` copied in at build time (FR-D-24) | App pipeline, `Jenkinsfile` | `<build>` | Deployment `game`, ≥ 2 replicas | Phase 1 |
| `<ns>/minotaur` | `minotaur/Dockerfile` | App pipeline when service code changes; model pipeline, `Jenkinsfile.model`, when a model passes all gates (FR-M-13) | `<build>` from the app pipeline; `model-<build>` from the model pipeline | Deployment `minotaur`, 2–10 replicas under the HPA | Phase 1 |
| `<ns>/frontend` | `frontend/Dockerfile` (nginx serving the canvas page) | App pipeline | `<build>` | Deployment `frontend` behind the Ingress | Phase 1 placeholder or Phase 2 |
| `<ns>/trainer` | `model/` | Model pipeline | Model pipeline build number (form fixed in Phase 4) | Kubernetes Job (FR-D-15) | Phase 4 |

Images that need **no** repository of ours:

- **Sim bots** (`simbots/`) run on the Jenkins host through Docker Compose
  for the integration test and the load test, so they are built locally and
  never pulled by the cluster. Add a repository only if that changes.
- **Elasticsearch, Logstash, Kibana, Filebeat, NGINX Ingress** are
  official upstream images.

Create the first three repositories now (the Build Plan's Phase 0 Dev B
task). Create `trainer` in Phase 4, once the Job's design is settled.

## Tagging rules

- Every image is tagged with the **Jenkins build number** (`BUILD_NUMBER`)
  of the pipeline that built it (SRS 2.4, 6.2 step 8). The model pipeline
  prefixes it: `minotaur:model-<build>` (FR-M-13). The app pipeline and the
  model pipeline count builds separately, and the `model-` prefix keeps
  their tags in the same `minotaur` repository from colliding.
- **`latest` is never deployed** (SRS 2.4). The pipelines should not push
  it at all, and no Kubernetes manifest or Ansible variable may reference
  it. Kubernetes rolls out only when the image tag changes (Build Plan
  Phase 1 risk), and a build-number tag also makes every running pod
  traceable to its build (NFR-11).
- Tags are never overwritten. A rebuild is a new build number.
- Rollback is `kubectl rollout undo` to the previous tag (FR-M-15). The
  previous tag must therefore stay on Docker Hub: do not set a cleanup
  policy that deletes recent tags.

## Creating the repositories (manual, Docker Hub web UI)

The Docker CLI cannot create repositories. Pushing an image creates one
implicitly, but creating them up front fixes the visibility and
description before the pipeline's first push.

For each of `game`, `minotaur` and `frontend`:

1. Sign in at <https://hub.docker.com> as the account that owns `<ns>`.
2. **Repositories** → **Create a repository**.
3. **Namespace:** `<ns>`. **Repository name:** `game` (then `minotaur`,
   then `frontend`).
4. **Short description:** for example `Minotaur Maze game server, tagged by
   Jenkins build number`.
5. **Visibility: Public** (recommended). No secret is ever baked into an
   image (NFR-07), and public images need no image-pull secret in
   Minikube. If you choose Private, check your plan's private-repository
   limit, and add an `imagePullSecret` to the Deployments in Phase 1.
6. **Create**.

## The token Jenkins pushes with (FR-D-21)

1. Docker Hub → **Account settings** → **Personal access tokens** →
   **Generate new token**. Description `jenkins-minotaur-maze`, access
   **Read & Write**.
2. Copy the token once. It is not shown again.
3. Jenkins → **Manage Jenkins** → **Credentials** → **System** → **Global
   credentials** → **Add credentials**. Kind **Username with password**:
   username `<ns>`, password = the token, ID for example `dockerhub`.
   The Jenkinsfile then refers to this ID, never to the token.
4. Never put the token in the repository, a Jenkinsfile, a Dockerfile, a
   manifest or `.env.example`.

## Verify

Public repositories can be checked without logging in:

```sh
for r in game minotaur frontend; do
  printf '%-10s ' "$r"
  curl -s -o /dev/null -w '%{http_code}\n' "https://hub.docker.com/v2/repositories/<ns>/$r/"
done
# 200 = exists, 404 = missing
```

In the Docker Hub UI, the Phase 1 gate also expects to see a tag equal to a
Jenkins build number in each repository after the first pipeline run.
