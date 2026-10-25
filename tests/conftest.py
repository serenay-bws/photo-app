import os
import sys
import tempfile
from pathlib import Path

# Testdata in een tijdelijke map, nooit in de echte data/-map
os.environ["FOTOSTUDIO_DATA"] = tempfile.mkdtemp(prefix="fotostudio-test-")
os.environ.setdefault("FOTOSTUDIO_ENGINE", "cpu")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
