# Description: Progress reporting to stderr and strict credential/secret protection
- **Progress & secrets:** Print periodic progress to `stderr` on long waits. Never print secret files/tokens or enable `set -x` around credentials; if a credential is ever pasted into chat, tell the user at once to rotate it.
