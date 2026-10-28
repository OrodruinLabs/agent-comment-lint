"""Lets `python3 -m agent_comment_lint` run the check."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
