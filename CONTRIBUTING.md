# Contributing to Minotaur Maze

Three people build this project in parallel (see
[`docs/BUILD_PLAN.md`](docs/BUILD_PLAN.md)). `main` is always deployable: every
push to it triggers the Jenkins pipeline. This page is how work gets there.

The specification is [`docs/SRS.md`](docs/SRS.md). Requirement IDs (FR-G-…,
FR-M-…, FR-D-…, NFR-…) are the shared vocabulary in branch names, commits and
PRs.

## Workflow

1. **Sync `main`.**
   ```sh
   git switch main && git pull --ff-only
   ```
2. **Branch, one task per branch.** Name it `<type>/<short-description>`,
   with the requirement ID if there is one:
   ```sh
   git switch -c feat/fr-g-08-line-of-sight
   ```
   Types: `feat`, `fix`, `test`, `docs`, `infra`, `ml`, `chore`.
3. **Commit in your own name, often.** Commit history by every member is
   graded (CR-01, FR-D-02). Check yours once per machine:
   ```sh
   git config user.name && git config user.email
   ```
   Messages follow `<type>(<area>): <what>`, for example
   `feat(game): reject Minotaur moves into safe zones (FR-G-05)`.
4. **Push at the end of every day**, even unfinished, so no work lives on
   only one laptop:
   ```sh
   git push -u origin HEAD
   ```
5. **Open a pull request into `main`** when the branch's tests pass locally.
   The PR template asks for the requirement IDs, how you tested, and whether a
   shared contract changed.
   ```sh
   gh pr create --base main --fill   # or use the GitHub web UI
   ```
6. **Review.** Another team member approves before merge. Prefer the
   owner of the area the PR touches (ownership table in the Build Plan).
7. **Merge, then watch the pipeline.** Use a merge commit or rebase-merge,
   so every author's individual commits stay in `main`'s history. Squashing
   collapses them into one commit. Every merge triggers Jenkins. **If the
   pipeline goes red, whoever merged fixes it before starting anything
   else.**
8. **Delete the branch** after merge.

Never push directly to `main`. Once branch protection is on
([`docs/GITHUB_SETUP.md`](docs/GITHUB_SETUP.md)), GitHub enforces this.

## Shared contracts

Two contracts may only change with every affected owner agreeing, and with
`docs/SRS.md` updated in the same PR:

- **The Minotaur API** between `game/` and `minotaur/`. Its request schema
  must never carry the active exit (FR-G-04).
- **`features/`**, the one feature module imported by both `model/` and
  `minotaur/` (FR-M-23).

The same discipline applies to the log event schema (SRS Appendix B) and
the level (`levels/maze.json` and the `level` section of `config/game.yaml`),
because dashboards, training data and every model depend on them.

## Before opening a PR

For `game/`:

```sh
cd game
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

Other services add their own commands here as they are created.

Never commit secrets. `.env` is git-ignored; real values belong in
`.env` locally, in Ansible Vault (`ansible/group_vars/all/vault.yml`), or in
the Jenkins credentials store (FR-D-20 to FR-D-22). The pipeline's gitleaks
stage fails the build on any finding.

## Where things go

The layout follows SRS Appendix A. Folders are created by the phase that
first needs them. They are not created empty in advance, which would only
invite merge conflicts between parallel branches.

| Path | Purpose | Owner | Status |
|---|---|---|---|
| `docs/` | SRS, Build Plan, setup guides | everyone | present |
| `game/` | FastAPI game server: rules, loop, WebSocket | Dev A | Phase 0 scaffold |
| `levels/` | The one level file | Dev A | present |
| `config/game.yaml` | Tunable game settings, baked into the image | Dev A | present (level settings only) |
| `elk/`, `docker-compose.elk.yml` | Logstash pipeline, ELK stack | Dev C | present |
| `frontend/` | Canvas game page, served by nginx | Dev A | Phase 1 placeholder or Phase 2 |
| `simbots/` | Sim bots, bot runner, load test | Dev A | Phase 2 |
| `minotaur/` | Minotaur service: model, hunting, fallback | Dev C | Phase 1 |
| `features/` | Shared feature extraction | Dev C | Phase 4 |
| `model/` | Trainer, gates, `config.yaml` | Dev C | Phase 4 |
| `k8s/` | Deployments, Services, Ingress, HPA, Job, DaemonSet | Dev B | Phase 1 |
| `ansible/` | `site.yml`, `deploy.yml`, seven roles | Dev B | Phase 1 |
| `Jenkinsfile`, `Jenkinsfile.model` | App and model pipelines | Dev B | Phase 1 / Phase 4 |
| `docker-compose.yml` | Local app stack | Dev B | Phase 2 |

Docker images and their Docker Hub repositories are listed in
[`docs/DOCKER_HUB.md`](docs/DOCKER_HUB.md).
