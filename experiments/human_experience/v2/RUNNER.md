# v2 MCP runner guide (for subagents)

Work from `/home/user/UserSim`. Call the UserSim MCP only through this exact command form (it is pre-approved):

```
.venv/bin/python experiments/human_experience/mcp_client.py call <tool> '<json args>' --brief
```

`--brief` prints `[session_id] step N left M | url | title` and the visible fields with their x,y. Screenshots are
saved under `experiments/human_experience/results/mcp_shots/` and the path is printed; Read one when the field list
is not enough. Errors come back as `{"error": ...}` text, not exceptions.

Rules (from the server):
- One action per `usersim_act` call, each with an honest first-person `thought`.
- Coordinates are pixels in a 1280x800 screenshot; use the x,y printed for fields.
- Email signup only; never Google, GitHub, Microsoft or Apple sign-in. Never type any email except the one the
  server gives you. Never invite real people, send messages outside the product, pay, upgrade or start a trial
  that needs a card. If the free plan blocks a step, note it and move on.
- CAPTCHAs: try the checkbox like a person would, then call `usersim_solve_captcha`. Wait out spinners
  (`{"type":"wait","ms":4000}`) instead of clicking submit again.
- Verification mail: `usersim_wait_for_verification_code` / `usersim_wait_for_verification_link` (call again if
  not found; mail can take 1-3 minutes), then type the code or `usersim_open_verification_link` with the URL.
- Always end with `usersim_finish` (outcome `completed`, `gave_up` or `blocked`, with honest notes).
- Do not print or save passwords anywhere.
