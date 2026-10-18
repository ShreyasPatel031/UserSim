"""UserSim over MCP: a coding agent (Claude Code) is the simulated user.

UserSim owns the browser (our Browserbase account), runs every action on the
real page, records the trace into an ordinary Study, judges the outcome, and
returns the report. The client only decides the next action.
"""
