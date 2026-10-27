"""Run an experiment file: python -m simlab.run simlab/experiments/<name>.py
An experiment file defines NAME, optional UNDATED (inputs that could include the future), NOTES, and scores() ->
DataFrame with `id` + score columns. The harness tests it against the baseline and logs it to registry.jsonl."""
import importlib.util, sys
from . import harness

spec = importlib.util.spec_from_file_location("exp", sys.argv[1]); E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)
harness.evaluate(E.NAME, E.scores(), getattr(E, "UNDATED", ()), getattr(E, "NOTES", ""))
