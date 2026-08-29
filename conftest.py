import sys
from pathlib import Path
import gltest.direct.sdk_loader as sl

# Ensure GenLayer SDK paths are in sys.path
sl.setup_sdk_paths()

# Ensure workspace root is in sys.path
workspace_root = Path(__file__).parent
if str(workspace_root) not in sys.path:
    sys.path.insert(0, str(workspace_root))
