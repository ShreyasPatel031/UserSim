# MCP loop review: Oct 13

Haiku agents (Claude Code `claude -p --model haiku`) used the public MCP at `https://atelier-sim.com/mcp`
as simulated users in full studies on sites never seen before: 1 product, 2 rivals, 6 personas, 6 tasks,
two of each aimed at each site, 108 runs. After each study I read the traces, fixed the MCP and the
harness, deployed, and ran the next study on new sites.

Driver: `scripts/mcp_loop/run_study.py`. Trace summary: `scripts/mcp_loop/analyze.py`. Deploy:
`scripts/mcp_loop/deploy_vm.sh`. Specs: `scripts/mcp_loop/specs/`.

"Unseen" means not in any of the 1,166 studies in `gs://usersim-bakeoff-347838016394/mvp_studies/`, not
in any branch of the repo, and no mail from the site in the shared signup inbox.

## Results

<!-- STUDY TABLE -->

## Fixes, in the order the traces found them

<!-- FIX LIST -->

## Open questions for you

<!-- QUESTIONS -->

## Known issues not fixed

<!-- KNOWN -->
