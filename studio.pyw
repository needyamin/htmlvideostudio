import os
import sys
import traceback
from pathlib import Path

# crash log next to this file (helps support without a console window)
_err_log = Path(__file__).resolve().parent / "studio_error.log"
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from studio.app import main
    main()
except Exception:
    try:
        _err_log.write_text(traceback.format_exc(), encoding="utf-8")
    except Exception:
        pass
    raise
