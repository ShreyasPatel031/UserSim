# Evidence for the dataset URL fixes (build.py `URL_OVERRIDES`)

Each fix was checked against the source page given in the dataset's `source` field, and the image was looked at.

| pair | dataset problem | fix | evidence |
|---|---|---|---|
| 20, 21 | loser URLs under `goodui.org/.../files/5006/` return 404 | same file names under `files/5009/` and `files/5097/` | same leak (#47) image names; found by the earlier branch |
| 103 | `win_url = lose_url =` the VWO story page itself (not an image) | composite `static.wingify.com/gcp/uploads/2022/12/Human-Interest-2.png` (still live) | the 2023-06-04 Wayback snapshot of the story shows this image; the variation won (+75.84%) |
| 62 | the image is Etsy leak #109 (category links) filed under a Zalando URL; only one version | GoodUI leak #27 "Zalando Tests Black Add-To-Cart Buttons": A `files/4418/leak027_afull.jpg` (orange) > B `files/4419/leak027_bfull.jpg` (black) | rationale: "The orange button stands out more ... than the black button". GoodUI later added: "the outcome ... was flipped with black being the eventual implementation" (kept as `label_note`) |
| 149 | one image (Tinkoff test 2, variation 2) for both sides | win `2019/01/10.jpg` (V2, green bar, +12.8%), lose `2019/01/8.jpg` (V1, yellow bar, +6.9%) | page text: "the second variation improved conversion rates by an impressive 12.8%", V1 6.9%; ui_change Progress Bar Color/Size |
| 174 | one image (`teamleader-casestudy-2`, test 1 "No credit card required") | win `teamleader-casestudy-12.png` (test 4 variation, icons in form fields), lose `-11.png` (test 4 control) | rationale is about emoji icons in the form ("Icon: Presence"); test 4 "Introducing Icons in Form Fields Improved Conversions by 13.1%" |
| 228 | one image, and it is the CONTROL (`Readers-Product-Videos-CONTROL.png`) given as the winner | win `...-VARIANT.png`, lose `...-CONTROL.png` | page: product videos gave "a 10% increase in add to carts"; rationale: "The addition of product videos" |
| 269 | one image (`flos-casestudy-7`, the control) | win `flos-casestudy-9.png` (Variation 2), lose `-7.png` (control) | page: "Winner: Variation 2", "Control (No Color Swatches)"; rationale: color samples AND model options expanded |
| 270 | same single image as 269 | win `flos-casestudy-9.png` (V2), lose `-8.png` (V1: swatches only) | rationale only about the model options, which is the V2 vs V1 difference |

# Pairs whose dataset image was a composite or not a screenshot (edits.py `SOURCES`)

| pair | problem | fix |
|---|---|---|
| 118 | `win_url` is a 250 px logo; the "loser" image holds both versions with Control / Variation labels and the uplift | both versions cropped from that image, red marks removed |
| 121 | `win_url` is a comparison graphic (control + variation + caption "105%") | variation panel cropped; the separate control image resized to the same width |
| 167 | `win_url` is a composite (Control / Variation + "Category page visits increase") | both versions cropped from it (same scale); red box removed |
| 175 | `win_url` shows V1 and V2 with labels | V2 (sticky banner, the best performer) cropped; "Control C" label cropped off the loser |
| 189, 190 | `win_url` shows "Version 1 Crew Image" and "Version 2 Truck Image" side by side with labels | 189 = crew panel, 190 = truck panel; control resized to the same width |
