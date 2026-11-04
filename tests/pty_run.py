"""Run a shell command on a pseudo-terminal, typing this process's stdin into it.

macOS ``script`` sends end-of-file before the typed text arrives, so the tests
use this instead of ``script`` there.
"""

import os
import pty
import subprocess
import sys


def main() -> int:
    typed = sys.stdin.buffer.read()
    leader, follower = pty.openpty()
    child = subprocess.Popen(["sh", "-c", sys.argv[1]], stdin=follower, stdout=follower, stderr=follower,
                             close_fds=True)
    os.close(follower)
    os.write(leader, typed)
    while True:
        try:
            chunk = os.read(leader, 65536)
        except OSError:
            break
        if not chunk:
            break
        sys.stdout.buffer.write(chunk)
    sys.stdout.flush()
    return child.wait()


if __name__ == "__main__":
    sys.exit(main())
