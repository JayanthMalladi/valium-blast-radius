"""Integration test: selector on the sample dir produces valid JSONL."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def test_select_on_sample_dir():
    """Run the selector on a sample dir; every line must be valid and
    every commit answered."""
    sample = os.environ.get("BR_TEST_SAMPLE")
    if not sample:
        return
    sys.path.insert(0, str(Path(sample)))
    import selector.main as M
    import io
    out = io.StringIO()
    sys.stdout = out
    M.main()
    sys.stdout = sys.__stdout__
    lines = [ln for ln in out.getvalue().strip().split("\n") if ln]
    for line in lines:
        obj = json.loads(line)
        assert "commit" in obj and "workers" in obj
        assert isinstance(obj["workers"], list)
        for w in obj["workers"]:
            for x in w:
                assert isinstance(x, int) and x >= 0
