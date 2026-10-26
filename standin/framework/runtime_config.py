"""Runtime settings of a deployed environment, read once at import, with no fallback.

Only the oldest tests import it. Importing it needs ``STANDIN_RUNTIME_ROOT`` and the
``runtime.ini`` file there, so collecting those tests elsewhere (a sandbox) needs a stub.
"""

import configparser
import os

ROOT = os.environ["STANDIN_RUNTIME_ROOT"]
_PARSER = configparser.ConfigParser()
with open(os.path.join(ROOT, "runtime.ini"), encoding="utf-8") as handle:
   _PARSER.read_file(handle)
MODE = _PARSER.get("runtime", "mode")
