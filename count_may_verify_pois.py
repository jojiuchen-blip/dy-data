import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_may_verify_by_backend_pois as may_verify


print(len(may_verify.read_backend_pois()))
