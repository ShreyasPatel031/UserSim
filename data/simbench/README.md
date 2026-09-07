# SimBench data (local)

Downloaded from [pitehu/SimBench](https://huggingface.co/datasets/pitehu/SimBench).

```bash
PYTHONPATH=src python -m human_sim.simbench_setup
PYTHONPATH=src python -m human_sim.simbench_cost
```

Eval scripts live in `vendor/SimBench_release/` (gitignored clone of upstream).
