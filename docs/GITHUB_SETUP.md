# GitHub repository setup

One-time settings for `github.com/suryans77/Minotaur_Maze`. Only a repository
admin can change them. The everyday workflow is in
[`../CONTRIBUTING.md`](../CONTRIBUTING.md).

State as audited on 2026-11-26 through the GitHub API:

| Setting | State |
|---|---|
| Visibility | Public, so branch protection is available on the free plan |
| Branch protection on `main` | **Not enabled** (no classic rule, no ruleset) |
| PR template | Added in `.github/pull_request_template.md`. It takes effect once merged to `main` |
| Collaborators | `suryans77` (admin), `gathik-jindal` (write); `Aarpeet` invited, **invitation not yet accepted** |
| Webhook | Active, push events, `application/json`, to `https://<ngrok-dev-domain>/github-webhook/`; last deliveries returned 200 |
| Branches / PRs | Only `main`; no pull request opened yet |

## 1. Protect `main`

### Recommended settings, and why

| Setting | Value | Why |
|---|---|---|
| Require a pull request before merging | On | Work reaches `main` only through PRs (FR-D-02) |
| Required approvals | 1 | Someone other than the author reads every change (Build Plan: "Read before you merge") |
| Dismiss stale approvals when new commits are pushed | On | An approval covers the code that was actually reviewed |
| Require review from Code Owners | Off | There is no `CODEOWNERS` file yet |
| Require conversation resolution | On | Review comments are answered, not ignored |
| Require status checks to pass | **Off for now** | Jenkins does not report a commit status to GitHub yet. Turn this on in Phase 1, once the pipeline posts a status for PR branches, and select that check |
| Require linear history | Off | Merge commits keep every member's own commits in history (CR-01) |
| Do not allow bypassing the above settings (include administrators) | On | The rules apply to everyone, so the graded PR history is real. An admin can switch it off briefly in an emergency |
| Allow force pushes | Off | History on `main` is never rewritten |
| Allow deletions | Off | `main` cannot be deleted by accident |

Also, under **Settings → General → Pull Requests**, tick **Automatically
delete head branches**.

### In the GitHub web UI

1. Open the repository → **Settings** → **Branches**.
2. Click **Add classic branch protection rule**.
3. **Branch name pattern:** `main`.
4. Tick **Require a pull request before merging**, then under it:
   - **Require approvals**, set to **1**;
   - **Dismiss stale pull request approvals when new commits are pushed**.
5. Tick **Require conversation resolution before merging**.
6. Tick **Do not allow bypassing the above settings**.
7. Leave **Require status checks to pass before merging**, **Require linear
   history**, **Allow force pushes** and **Allow deletions** unticked.
8. Click **Create**.

### Or with the GitHub CLI (admin token)

```sh
gh api -X PUT repos/suryans77/Minotaur_Maze/branches/main/protection \
  -H "Accept: application/vnd.github+json" --input - <<'EOF'
{
  "required_status_checks": null,
  "enforce_admins": true,
  "required_pull_request_reviews": {
    "required_approving_review_count": 1,
    "dismiss_stale_reviews": true,
    "require_code_owner_reviews": false
  },
  "restrictions": null,
  "required_conversation_resolution": true,
  "required_linear_history": false,
  "allow_force_pushes": false,
  "allow_deletions": false
}
EOF
gh api -X PATCH repos/suryans77/Minotaur_Maze -F delete_branch_on_merge=true
```

### Verify

```sh
gh api repos/suryans77/Minotaur_Maze/branches/main --jq .protected      # true
gh api repos/suryans77/Minotaur_Maze/branches/main/protection --jq '{
  approvals: .required_pull_request_reviews.required_approving_review_count,
  dismiss_stale: .required_pull_request_reviews.dismiss_stale_reviews,
  admins_included: .enforce_admins.enabled,
  conversations: .required_conversation_resolution.enabled,
  force_pushes: .allow_force_pushes.enabled,
  deletions: .allow_deletions.enabled}'
```

Then confirm it bites: `git push origin HEAD:main` from a local commit
must be **rejected** with "protected branch".

**Order of operations.** Once this is on, nobody can push to `main`
directly, admins included. Commit pending work on a branch and merge it
through a PR. That PR doubles as the gate check that the workflow works.

### Phase 1 follow-up: required checks

When the app pipeline can build PR branches and report the result to
GitHub, turn on **Require status checks to pass before merging** and select
the Jenkins check by name. Until then, the "a failing test stops the
pipeline" guarantee comes from Jenkins on `main` (SRS 6.2), not from
GitHub.

## 2. Team access

Each of the three members needs **Write** access.

- `Aarpeet`: accept the pending invitation at
  <https://github.com/suryans77/Minotaur_Maze/invitations> (or from the
  email GitHub sent).
- Check: `gh api repos/suryans77/Minotaur_Maze/collaborators --jq '.[] | "\(.login) \(.role_name)"'`
  lists all three, and `gh api repos/suryans77/Minotaur_Maze/invitations --jq length` prints `0`.

### Clone, branch and PR check (Phase 0 exit gate)

Each member, on their own machine:

```sh
git clone https://github.com/suryans77/Minotaur_Maze.git
cd Minotaur_Maze
git config user.name && git config user.email      # your own identity
git switch -c chore/gate0-<your-github-login>
echo "- <your-github-login>" >> docs/team-check.txt   # any trivial change
git add docs/team-check.txt
git commit -m "chore: phase 0 clone/branch/PR check (<your-github-login>)"
git push -u origin HEAD
gh pr create --base main --draft --title "Phase 0 PR check: <your-github-login>" \
  --body "Gate check only. Close without merging."
```

Then close the PR without merging and delete the branch:

```sh
gh pr close --delete-branch <PR-number>
```

Done when `gh pr list --state closed --search "Phase 0 PR check"` shows
one PR per member.

## 3. Webhook

The webhook already exists and was not changed. To re-check it in the UI,
go to **Settings → Webhooks → (the ngrok URL) → Recent Deliveries**. Each
push should show a **200**. From the CLI:

```sh
HOOK=$(gh api repos/suryans77/Minotaur_Maze/hooks --jq '.[0].id')
gh api "repos/suryans77/Minotaur_Maze/hooks/$HOOK/deliveries?per_page=5" \
  --jq '.[] | "\(.delivered_at) \(.event) \(.status_code)"'
```
