# Atelier Sim plugin privacy policy

Last updated: November 17, 2026.

This policy covers the Atelier Sim plugin for Claude Code and the Atelier Sim MCP server it connects to
(`https://35-202-98-224.sslip.io/mcp`).

## What we receive
- The product URL you test, and the task and persona text you approved in Claude Code.
- Each browser action the simulated user takes and the short "thought" it writes for that action.
- Your client IP address, used only for rate limits and abuse prevention.

We do **not** receive your source code, your files, your Claude conversation, or any credentials of yours. Claude reads
your repository locally.

## What we do with it
- Open the product URL in a browser on Atelier Sim's own machines and record screenshots, steps and thoughts.
- Judge each run with an AI model (Google Gemini on Google Cloud).
- Sign up to your product, when the task needs it, with Atelier Sim-owned email aliases and a Atelier Sim phone number.
- If a captcha blocks a run, the page's captcha may be sent to a captcha-solving service.
- We do not sell the data and do not use it to advertise.

## Who can see it
A run's watch and report links open the run without login. Anyone you share a link with can see its screenshots, so
do not test pages that show private or personal data.

## Retention and deletion
Run reports, screenshots and steps are stored in Google Cloud Storage (US) and kept until you ask us to delete them.
To delete a run, open an issue at https://github.com/ShreyasPatel031/UserSim/issues with its study id. We
delete it within 30 days.

## Children
The plugin is not intended for people under 18.

## Changes
Changes to this policy are published in this file, with the date above.
