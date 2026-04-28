import sys
from pathlib import Path

# Add spec-based-ui/ to path so `from app import ...` works in all tests
sys.path.insert(0, str(Path(__file__).parent.parent))
