#!/usr/bin/env python3
"""Entry point for agent-comment-lint. Exits 0 clean, 1 on violations, 2 when it could not scan."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agent_comment_lint.cli import main

if __name__ == "__main__":
    sys.exit(main())
