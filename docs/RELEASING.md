# Releasing

A release is a git tag. The `release` workflow does the rest: tests, build, PyPI, GitHub Release.

## One-time setup (PyPI trusted publishing, no token in GitHub)

1. Create a PyPI account at https://pypi.org (enable 2FA).
2. https://pypi.org/manage/account/publishing/ → **Add a new pending publisher**:
   - PyPI project name: `brain-core`
   - Owner: `xy-claude` · Repository: `brain-core` · Workflow: `release.yml` · Environment: `pypi`
3. On GitHub: repo → Settings → Environments → **New environment** `pypi` (optionally require a reviewer).

The first tag push claims the project name on PyPI. From then on `uv tool install brain-core` works everywhere.

## Every release

```bash
# 1. version + changelog
sed -i '' 's/^version = ".*"/version = "0.2.1"/' pyproject.toml
sed -i '' 's/^__version__ = ".*"/__version__ = "0.2.1"/' src/brain_core/__init__.py
#    move items from "## [Unreleased]" to "## [0.2.1] - YYYY-MM-DD" in CHANGELOG.md
# 2. verify like CI does
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run pytest -q
# 3. commit, tag, push the tag
git commit -am "Release 0.2.1" && git tag v0.2.1 && git push origin main v0.2.1
```

The workflow refuses a tag whose version does not match `pyproject.toml`. Release notes are the matching CHANGELOG section.

## Checking

- https://github.com/xy-claude/brain-core/actions (release run green)
- https://pypi.org/project/brain-core/ (new version listed)
- `uv tool install --force brain-core && brain version`
