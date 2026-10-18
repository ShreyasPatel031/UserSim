# Armature (armature.tech): agent mode, 4 personas (18 Oct 2026)

- **Inputs:**
  - live scrapes of Armature, GitHub Copilot, Tabnine and Cursor (all four review sites, about $1.30);
  - `mvp.agent_mode.predict_experience` from main;
  - personas: DevRel lead, founder, growth marketer, engineer.
- **Output:** `armature_agent_mode.json`.

**Do not use as-is.** The identity gate passed 7 "Armature" reviews that are about **Armature Fabric**, an
accreditation platform, not armature.tech ("get discovered and used by coding agents"). The judge had no description
of the product, so it guessed a match. It also accepted Tabnine and Cursor as direct competitors on the same guess.

- **Ratings:** the overall 4.3 and recommend 8.4 are partly set by the wrong product.
- **Words:** "limited reporting" and "accreditation" come from Armature Fabric.
- **Fix needed in agent mode:** give the identity judge the product page's own description, then re-run.

## Re-run after PR #107 (the identity judge now sees the product page)

`armature_agent_mode_v2.json`: every persona returns `status: no_data`.
- The Armature Fabric reviews are rejected.
- GitHub Copilot, Tabnine and Cursor are judged not to be Armature's competitors.

That is the right outcome. armature.tech has no reviews of its own on the four sites, and these coding assistants do
not do its job. For a real prediction it needs competitors that do (developer-marketing or docs/discoverability tools),
or human mode.
