"""Allow: python3 -m tools.disassembler rom/SOR.bin ..."""

from .main import main
import sys

if __name__ == '__main__':
    sys.exit(main())
