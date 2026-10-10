# WiserUI-Bench: final clean image set (all 300 pairs)

Benchmark: https://github.com/jeochris/wiserui-bench (Jeon et al., arXiv 2505.05026, ACL 2026), CC BY-NC-SA 4.0.

**The authors never published cleaned images.** `dataset/DATA_POLICY.md` says they do not redistribute images. They
publish source URLs, a download script, and an inpainting script for GoodUI markers. Their README adds that "some
images may require manual cropping or editing". Every user rebuilds the images, so this directory is our rebuild,
done reproducibly. No images are committed; `build.py` regenerates them.

```bash
export WISERUI_CLEAN=/path/to/workdir            # images land in $WISERUI_CLEAN/final/{index}/{win,lose}.png
python bench/wiserui_clean/build.py              # clones the benchmark repo, downloads, cleans (~5 min, no model calls)
python bench/wiserui_clean/audit.py              # optional: Gemini 2.5 Flash leak audit, ~$0.60 uncached
```
Needs `opencv-python-headless`, `requests`, `Pillow`, `tqdm`; `audit.py` also needs `google-genai` and Vertex
credentials (`GOOGLE_CLOUD_PROJECT`).

| file | what |
|---|---|
| `build.py` | download + clean all 300 pairs; `URL_OVERRIDES` (9 dataset URL fixes); writes `manifest.json` |
| `markers.py` | GoodUI numbered-marker remover (catches what the repo's inpainting misses) and abtest.design A/B-badge remover |
| `edits.py` | hand-specified fixes per pair: re-crops (`SOURCES`), stroke / box removal, frame trims (`EDITS`) |
| `composite_split.jsonl` | panel boxes + winner for the 73 composite items (gemini-2.5-pro + manual hints, from `grokbot/pairwise-judge`) |
| `audit.py`, `audit.json` | leak audit of the final 600 images (same prompt and model as the earlier composite audit) |
| `manifest.json` | per pair: URLs used, every step applied, image sizes, audit flags and the review verdict |

## Result
- **300 / 300 pairs, nothing dropped.** By source: 103 GoodUI, 168 VWO, 29 abtest.design. 67 come from composite
  images (both versions in one graphic), 233 from separate images.
- Final audit: 50 pairs flagged. I reviewed every one by eye, and all 50 are kept as they are. Each is one of:
  - the page's own UI ("Best seller", "MOST POPULAR", "NEW", award badges);
  - a publisher mark that appears on **both** versions, so it does not point at the winner;
  - the VWO watermark, which is also on both versions.

  `manifest.json` has the verdict for each.
- Spend for this rebuild: ~$0.70 (audits only). The build itself makes no model calls.

## Compared with `grokbot/pairwise-judge` (the earlier cleaning)
| | grokbot/pairwise-judge | this set |
|---|---|---|
| pairs usable | 252 headline (270 Gemini-clean), 6 dropped as single-version | **300** |
| the 6 "single-version" pairs (62, 149, 174, 228, 269, 270) | dropped | recovered: they were dataset URL errors; the other version is on the source page (see FIXES.md) |
| 225 non-composite pairs | never audited | audited; 7 GoodUI pairs still had markers after the repo's inpainting (now removed); 26 VWO pairs had publisher arrows, boxes, labels, a dim overlay or a composite instead of one version (fixed) |
| VWO images through `process_image` | yes (repaints purple page content: 174 VWO / abtest images changed, up to 6.6% of pixels) | no: `process_image` only runs on GoodUI images, the only ones with its markers |
| composite crops | Gemini boxes as-is | same boxes, reproduced exactly; 8 re-cropped by hand where the box took in labels, result banners or the next panel; 29 composite pairs got further hand fixes (highlight boxes, frame lines, callouts) |
| abtest.design A/B badges | 6 flagged by hand, left in | removed automatically on all 29 (gray = control, blue = variant) |
| leak fixes | Nano Banana edits (15 fixed / 13 still leaked / 5 damaged); outputs not committed, not reproducible | deterministic crops / inpainting / color-stroke removal, every edit checked on a changed-pixel overlay |
| reproducible from the repo | no (images and edit outputs lived on another machine) | yes |

## Caveats
- Label for 62: GoodUI later wrote that the result "was flipped with black being the eventual implementation". The
  dataset keeps orange as the winner and so does this set (`label_note` in the manifest).
- 121, 167, 175, 189 and 190: the winner exists only as a panel inside a comparison graphic. It is cropped from there.
  Where the loser came from a separate, larger image (121, 189, 190), it is resized to the same width.
- Inpainted areas leave soft smudges where annotations were. They sit where the publisher pointed, often at the
  changed element, so a smudge could hint at the location of the change, though not at the winner.
- The leak audit is one Gemini 2.5 Flash pass. It missed cues before, so I also reviewed every composite and every
  edited image by eye. Subtle cues may remain.
