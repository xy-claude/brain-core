# Releasing

A release is a git tag. The `release` workflow does the rest: tests, build, PyPI, GitHub Release.

## One-time setup (PyPI trusted publishing, no token in GitHub)

1. Create a PyPI account at https://pypi.org (enable 2FA).
2. https://pypi.org/manage/account/publishing/ → **Add a new pending publisher**:
   - PyPI project name: `brain-core-mcp` (PyPI rejects `brain-core` as too similar to `braincore`)
   - Owner: `xy-claude` · Repository: `brain-core` · Workflow: `release.yml` · Environment: `pypi`
3. On GitHub: repo → Settings → Environments → **New environment** `pypi` (optionally require a reviewer).

The first tag push claims the project name on PyPI. From then on `uv tool install brain-core-mcp` works everywhere.

## Every release

```bash
# 1. version in the five places that carry it, then the changelog (OLD is the current version)
OLD=0.2.1 NEW=0.2.2
sed -i '' "s/^version = \"$OLD\"/version = \"$NEW\"/" pyproject.toml
sed -i '' "s/^__version__ = \".*\"/__version__ = \"$NEW\"/" src/brain_core/__init__.py
sed -i '' "s/\"version\": \"$OLD\"/\"version\": \"$NEW\"/g" server.json      # two places
sed -i '' "s/-Ref v$OLD/-Ref v$NEW/" install.ps1                              # the usage example
uv lock                                                                       # uv.lock names the version too
#    in CHANGELOG.md add "## [0.2.2] - YYYY-MM-DD" under "## [Unreleased]", above its items
git diff --stat          # expect six files: CHANGELOG.md install.ps1 pyproject.toml server.json __init__.py uv.lock
# 2. verify like CI does (mypy with no path: it checks the tests too)
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run pytest -q
# 3. commit, tag, push the tag
git commit -am "Release 0.2.2: what changed" && git tag v0.2.2 && git push origin main v0.2.2
```

Convention: one commit per release, subject `Release X.Y.Z: what changed`, and the tag sits on that commit, never on a later one. Release runs are titled `Release vX.Y.Z` from the tag; test runs are titled by the commit subject. The workflow refuses a tag whose version does not match `pyproject.toml`. Release notes are the matching CHANGELOG section.

## Checking

- https://github.com/xy-claude/brain-core/actions (release run green)
- https://pypi.org/project/brain-core-mcp/ (new version listed)
- `uv tool install --force brain-core-mcp && brain version`

PyPI's JSON page can show the old version for a minute after the upload. The README on PyPI is the one in the tagged commit, so README changes made after a release show there only with the next one.
