# Dynalist (dynalist.io): no-token MCP e2e

Report: [https://usersim.vercel.app/report?study=ab9fa612-f223-4ec8-bcff-5087400f3420](https://usersim.vercel.app/report?study=ab9fa612-f223-4ec8-bcff-5087400f3420) · Persona: Marcus Lee, a freelance product designer who plans in outlines · Engine 3f2b4fbd

**Result: signup ✅ (email link), 3/3 tasks ✅.** Task 4 passed (judge + proof) on rerun [4ab5be34](https://usersim.vercel.app/report?study=4ab5be34-d6b4-4848-aa69-cae94dba97f7) on engine b0f7eecd. The 2 runs before it were done in the browser too, but failed on judge bugs, now fixed (below).

## Signup (cell t1, 8 steps), verified by **email link**
1. SIGN UP form: name, email (MCP alias), password. No captcha.
2. A green box says "You're in! We've sent an account activation email". ![sent](shots/dynalist-t1-activation-sent.jpg)
3. `usersim_wait_for_verification_link` got "Dynalist Email Confirmation" with one *Confirm your email* link. `usersim_open_verification_link link_number=1` opened it.
4. The login page says "Email confirmation success!" with the email prefilled. ![confirmed](shots/dynalist-t1-email-confirmed.jpg)
5. Typed the password and landed in the app on *Getting started with Dynalist* with a Welcome modal.

![signed in](shots/dynalist-t1-signup-final.png)

## Tasks
| Cell | Task | Steps | Result |
|---|---|---|---|
| t2 | Create document *Website Redesign Plan* | 20 | ✅ sidebar + › New document, renamed from the title, synced; kept after a reload |
| t3 | Add Research, Wireframes (with Homepage sketch under it), Launch | 18 | ✅ Enter / Tab / Shift+Tab; kept after a reload |
| t4 | Check off Research | 11 / 14 / 14 | ✅ final rerun 4ab5be34: item menu › Check off, struck through after a reload; judge reached, proof PASS |

![doc](shots/dynalist-t2-document-final.png)
![outline](shots/dynalist-t3-outline-final.png)
![checked off](shots/dynalist-t4-rerun2-checked-off-final.png)

## Why task 4 needed reruns (judge bugs, fixed)
| Run | Judge | Root cause | Fix |
|---|---|---|---|
| ab9fa612 | "did not check off the 'Research' item" (6/6 on the real frame) | Dynalist shows done as faint struck-through text; innerText drops it, and the vision model missed it | **9928cd7**: done-state facts read from the page, and the prompt says struck-through means completed (6/6 PASS; unstruck negative 0/6) |
| 6782d34e | same | The reader looked for struck *text nodes*, but Dynalist strikes a wrapper (`.Node.is-checked` › `.Node-content`), so it found nothing | **b0f7eec**: read the wrapper's text and done-like classes; checked on the live page (`marked done by its class (Node is-checked): "Research"`) |
| 4ab5be34 | **reached**: "the 'Research' item … is marked as completed" | n/a | deployed b0f7eecd |

## Actionable findings (Dynalist UX)
1. **Unsynced edits are dropped on reload without warning.** I renamed the new document in the sidebar, reloaded about 2 s later, and it was *Untitled* again. The only sign was a small grey "Sync now" in the corner. ![lost](shots/dynalist-t2-rename-lost-after-reload.jpg)
2. **Confirming the email doesn't sign you in**: you type the password again right after signing up.
3. The login form shifts down when the red "What's your email?" banner appears, so the field you aimed at moves.
4. The **Sign up** button (and Google button) aren't exposed as buttons to assistive tech or automation.
5. Check off is buried: the item menu icon appears only on hover, and the menu has 20+ entries. Plain bullets have no checkbox until you choose *Add checkbox*.
6. The help/shortcut panel is open by default and takes about 25% of the width on first use.
7. The Welcome modal ("special gift afterwards") interrupts the first document.

## MCP issues this product exposed
- Judge missed the struck-through "done" state → 9928cd7 + b0f7eec.
- My own login helper typed before the login page finished loading. The fix is a wait plus reading field positions from `fields`; there's no MCP change.
