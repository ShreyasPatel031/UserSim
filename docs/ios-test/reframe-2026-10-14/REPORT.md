# UserSim iPhone study: Reframe (iOS), Oct 14 2026

**Persona:** "Sam", 34, self-employed, wants to cut back on drinking, not quit.
**Device:** BrowserStack App Automate, iPhone 15 on iOS 17.4, session `9a8c16268aa0c5ec4ddeb7df62d2f6354640872c`, about 29 min (1752 s), Free plan.
**App:** Reframe: Drink Less & Thrive, by Glucobit Inc., bundle id `com.glucobit.cravingBuster.CravingBuster`, 4.5 stars from 45K ratings.

## Result: blocked at the trial step (no payment method on the Apple ID)

| Step | Outcome | Screenshot |
|---|---|---|
| Open App Store, search, find Reframe | pass | shots/003_results.png |
| Apple ID sign-in and SMS 2FA | pass on the 4th code. The first three were rejected because each new request cancelled the earlier codes. | shots/004..019 |
| Install Reframe (free) | pass | shots/019_after2fa_g.png |
| Create Reframe account (usersim.signups+reframe-ios-1014@gmail.com) | pass | shots/031_signup.png |
| Email confirmation code | pass. Read over the VM, because IMAP is blocked from the box. | shots/037_confirmed.png |
| Onboarding quiz, about 45 questions | pass | shots/038..112 |
| Paywall ("Design Your Trial") | It defaults to **30 Days for $4.99**, a charge. I switched to **7 Days, Free**, then a yearly plan at $99.99 per year. | shots/112, 113_paywall_7free.png |
| Apple purchase sheet | "1-week free trial, Starting today; $99.99 per year Starting Oct 21, 2026" | shots/114_redeem.png |
| Authorize with Apple ID password | accepted | shots/115, 116 |
| **Start trial** | **BLOCKED: "Payment Information Required. To subscribe, add a new payment method."** Cancelled, and nothing was charged or subscribed. | shots/117_sub_done.png, 118 |
| Core features | not reachable. The app reopens to the paywall flow. | shots/121_relaunch.png |

## UX findings (the persona's view)
- **Friction, dark pattern:** the paywall pre-selects the paid "30 Days, $4.99" option. The free 7-day option sits next to it. After the trial, it defaults to the yearly plan.
- **Strength:** the "No payment now" and "Easy, 1 click cancel" wording, plus a trial-reminder switch, are clear once the free option is chosen.
- **Friction:** the onboarding is very long, about 45 screens before any value, including 2 medication/GLP-1 upsell screens.
- **Strength:** the personalized plan and savings estimates ($2,860 a year) are motivating.
- **Friction:** the Reframe account needs an emailed 6-digit code before onboarding starts.

## Trial
Not started: no subscription and no charge. If it is started later: $0 for 7 days, then $99.99 per year. Started on Oct 14, it would renew Oct 21, 2026. Cancel at least one day earlier under Settings → Apple Account → Subscriptions.

## Needed to finish
Add a payment method (card) to the Apple ID shreyashfs@gmail.com, at appleid.apple.com or on your iPhone. Then rerun from the paywall. The Reframe account already exists, so the next run can log in and skip the quiz.
