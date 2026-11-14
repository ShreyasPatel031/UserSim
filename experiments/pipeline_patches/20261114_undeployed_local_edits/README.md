# Undeployed local edits (saved 2026-11-14)

The branch head was set to the code the VM runs (features.py 981c5ded, llm.py 046ee76c)
so head matches production. These patches hold the local edits that were never deployed:

- features.py.patch: extra feature files (ps_/vs_/pf_/psp_/pst_/psh_/psq_/tpc_/tpd_/cmp_/tmc_/tmd_/upw_),
  raw_fields carry-everything column, redacted maker id "0" guard (RED set). Not model inputs of arm 2.
- llm.py.patch: token refresh every 5 min and on 401.

Apply with `git apply` from the repo root; deploy only on Shreyas's word.
