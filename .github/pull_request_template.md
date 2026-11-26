## What this changes

<!-- One or two sentences. What does the system do after this PR that it did not before? -->

## Requirements

<!-- SRS v2 IDs this implements or affects, e.g. FR-G-08, FR-D-12, NFR-09. Write "none" for chores. -->

## Area

<!-- Tick every folder this PR touches. Owners are in docs/BUILD_PLAN.md ("Team and ownership"). -->

- [ ] `game/`, `frontend/`, `levels/`, `simbots/`, `config/game.yaml` (Dev A)
- [ ] `Jenkinsfile*`, `*/Dockerfile`, `docker-compose*.yml`, `k8s/`, `ansible/` (Dev B)
- [ ] `elk/`, `minotaur/`, `model/`, `features/` (Dev C)
- [ ] `docs/`

## How it was tested

<!-- Commands you ran and what they showed. For infrastructure, the command and its output. -->

## Checklist

- [ ] Tests pass locally for every service touched (for `game/`: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`)
- [ ] No secret, token, password or `.env` file is added; secrets go in Ansible Vault or the Jenkins credentials store (NFR-07)
- [ ] Images, if any, are tagged with the Jenkins build number; nothing deploys `latest` (SRS 2.4)
- [ ] Balance values are changed in `config/game.yaml`, not in code (FR-D-24)
- [ ] Docs updated where behaviour, setup or commands changed

## Shared contracts

<!-- Changing any of these needs the other owners' review and an SRS update in this same PR. Leave unticked if untouched. -->

- [ ] The Minotaur API (its request schema must never carry the active exit, FR-G-04)
- [ ] `features/`, the shared feature module (FR-M-23)
- [ ] The log event schema (SRS Appendix B)
- [ ] The level: `levels/maze.json` or the `level` section of `config/game.yaml`
- [ ] **If any box above is ticked:** `docs/SRS.md` is updated in this PR
