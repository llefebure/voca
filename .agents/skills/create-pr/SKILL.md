---
name: create-pr
description: Create a GitHub pull request using the gh CLI. Use when asked to create a PR, open a pull request, or submit changes for review.
---

# Create Pull Request Workflow

Follow these steps in order whenever creating a pull request:

## 1. Verify Branch & Safety Guardrails
- Check the current branch name:
  ```bash
  git branch --show-current
  ```
- **CRITICAL:** Never create a PR directly from `main`. If currently on a default branch, create and switch to a descriptive feature branch first (`git checkout -b feat/short-description`).
- Ensure all intended changes are committed and there are no unintended untracked files (`git status`).

## 2. Sync & Push Changes
- Fetch the latest remote state and check if the branch needs rebasing onto `origin/main` (only rebase if cleanly applicable or requested):
  ```bash
  git fetch origin
  ```
- Push the current branch to the remote repository:
  ```bash
  git push -u origin HEAD
  ```

## 3. Draft the PR Title & Description
- **Title:** Format the title using Conventional Commits (`<type>(<scope>): <succinct description>`), such as `feat(auth): add OAuth token refresh` or `fix(api): handle empty payload`.
- **Template:** Follow this template for the PR description:
    ```markdown
    ## Summary
    - Concise explanation of what changed and why.

    ## Changes
    - Bullet list of key technical modifications.

    ## Testing
    - [ ] Unit/integration tests pass
    - [ ] Manual verification completed
    ```

## 4. Create the PR via `gh` CLI
- **Avoid shell-escaping bugs:** Always write the PR description to a temporary file instead of passing multi-line Markdown directly to `--body`.
- Write the drafted body to `/tmp/pr-body.md`, run `gh pr create`, and remove the temp file:
  ```bash
  gh pr create \
    --title "<type>(<scope>): <description>" \
    --body-file /tmp/pr-body.md \
    --base main
  rm -f /tmp/pr-body.md
  ```
  **(Note: Add `--draft` if the user asks for a draft or work-in-progress PR**

## 5. Return Output
- Output the clickable Markdown link to the newly created PR returned by the CLI (e.g., `Created PR [#123](https://github.com/owner/repo/pull/123)`).
