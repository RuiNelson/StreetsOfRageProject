"""Allow: python3 -m tools.speculative_scan output/sor.map rom/SOR.bin ..."""

import sys

from .main import main

if __name__ == '__main__':
    sys.exit(main())
