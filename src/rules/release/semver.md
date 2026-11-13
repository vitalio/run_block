# Description: Semantic Versioning and release tagging rules (PATCH / MINOR / MAJOR)
- **Versioning & releases (SemVer):**
  - `PATCH` (`0.Y.Z+1`) — bugfixes, UI/box tweaks, and `--agents`/`--help`/docs updates.
  - `MINOR` (`0.Y+1.0`) — new CLI commands/flags or config options.
  - `MAJOR` (`X+1.0.0`) — breaking changes or only when explicitly requested.
  - Keep `VERSION` and in-code `VERSION = "..."` in sync, reinstall locally if applicable, commit, push to `origin {main_branch:main}`, and push an annotated release tag (`git tag -a vX.Y.Z -m "Release vX.Y.Z" && git push origin vX.Y.Z`).
