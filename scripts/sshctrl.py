#!/usr/bin/env python3
"""SSH Remote Control CLI. Implementation is in sshctrl_lib/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sshctrl_lib.cli import main

if __name__ == "__main__":
    main()
