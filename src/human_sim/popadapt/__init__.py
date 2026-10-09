"""Portable population adapter: one response contract, one interpretability engine, one evaluation.

contract.py  ResponseTable: units (groups or people, with attributes) x items (questions, products) -> answer distributions
adapters.py  dataset -> ResponseTable (SimBench group cells, Twin-2K-500 people). New data = new adapter, nothing else.
engine.py    low-rank axes ("reasons"), segments, anchor-based prediction for new items, coverage
evaluate.py  held-out evaluation with baselines, stability and faithfulness tests; writes an evaluation card per dataset
"""
