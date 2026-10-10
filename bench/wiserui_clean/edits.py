"""Hand-specified fixes for what build.py's automatic steps leave behind (FIXES.md gives the reason for each entry).

Every entry was decided by looking at the image after the Gemini leak audit (audit.py) flagged it, or in the manual
review of contact sheets. Coordinates are pixels, (x0, y0, x1, y1), end-exclusive.

SOURCES[i][side] = (raw, box) builds that side by cropping box out of a downloaded raw image instead of the default
  ("win" / "lose" = the image at that dataset URL, "composite" = the composite for win_url == lose_url pairs).
  Used to re-crop composite panels that took in labels, result banners or the neighbouring panel, and for pairs whose
  dataset URL points at a composite (both versions + labels / uplift) instead of one version.

EDITS[i] = [op, ...] applied in order after the image is built:
  ("crop", side, box)                     keep only box
  ("inpaint", side, [boxes])              OpenCV Telea inpaint inside the boxes
  ("fill", side, [boxes], bgr)            paint the boxes one flat color
  ("strokes", side, rgb, dh, region[, minlen[, maxw]])
                                          remove publisher strokes of one color (outlines, ellipses, arrows):
                                          saturated pixels within dh hue units of rgb that form a long (>= minlen,
                                          default 60 px) shape with mean stroke width <= maxw (default 9 px); dilated
                                          and inpainted. region limits it (None = whole image); every entry below
                                          was checked on a changed-pixel overlay so page content of the same color is
                                          left alone
  ("blob", side, rgb, dh, region)         every saturated pixel of that hue in region (filled tags, arrow heads)
  ("match_width", side, other)            resize side to the width of other (same scale for both versions)
  ("trim_frame", side, maxd)              crop inward past VWO frame lines / tab stubs at the image edges (saturated
                                          orange, pink, purple or blue rows/columns within maxd px of an edge; VWO
                                          frames the variation orange/pink/purple and the control blue)
  ("undim", side, factor, keep)           undo a publisher's uniform dark overlay (page = pixel / factor) everywhere
                                          except the spotlight box keep, which was left undimmed
side is "win", "lose" or "both".
"""
from __future__ import annotations

import cv2
import numpy as np

PINK = (226, 12, 110)  # VWO case-study callouts
RED = (245, 15, 15)

SOURCES: dict[int, dict[str, tuple[str, tuple[int, int, int, int]]]] = {
    # composites re-cropped tighter than composite_split.jsonl (its boxes took in labels / banners / other panels)
    106: {"win": ("composite", (1219, 478, 1482, 1110)), "lose": ("composite", (82, 476, 348, 1110))},
    107: {"win": ("composite", (1321, 519, 1608, 1140)), "lose": ("composite", (87, 516, 375, 1157))},
    119: {"win": ("composite", (205, 1040, 2235, 2140)), "lose": ("composite", (110, 400, 1690, 930))},
    166: {"win": ("composite", (1124, 260, 2482, 998)), "lose": ("composite", (72, 260, 1078, 798))},
    202: {"win": ("composite", (1278, 494, 2411, 2908)), "lose": ("composite", (150, 494, 1018, 2334))},
    215: {"win": ("composite", (1124, 260, 2482, 998)), "lose": ("composite", (72, 260, 1070, 798))},
    221: {"win": ("composite", (905, 314, 1649, 982)), "lose": ("composite", (108, 314, 835, 982))},
    254: {"win": ("composite", (1142, 322, 2062, 922)), "lose": ("composite", (124, 322, 1008, 838))},
    # the dataset URL is a composite (labels + uplift), or the winner URL is not a screenshot at all (118: a logo)
    118: {"win": ("lose", (670, 50, 1160, 1072)), "lose": ("lose", (130, 50, 620, 1072))},
    121: {"win": ("win", (322, 46, 613, 386))},
    167: {"win": ("win", (40, 862, 1249, 1449)), "lose": ("win", (40, 41, 1249, 628))},
    175: {"win": ("win", (36, 1068, 1250, 1948)), "lose": ("lose", (30, 35, 1260, 922))},
    189: {"win": ("win", (23, 108, 743, 755))},
    190: {"win": ("win", (766, 108, 1486, 755))},
}

EDITS: dict[int, list[tuple]] = {
    103: [("trim_frame", "both", 90)],
    104: [("strokes", "win", PINK, 8, (40, 930, 540, 1150), 60, 14),
          ("crop", "win", (9, 0, 1360, 1487)), ("crop", "lose", (0, 11, 909, 987))],
    109: [("strokes", "lose", RED, 8, None)],
    111: [("strokes", "lose", RED, 8, None)],
    112: [("fill", "win", [(382, 344, 500, 395), (410, 395, 453, 447)], (255, 255, 255))],
    117: [("trim_frame", "both", 90)],
    118: [("strokes", "win", RED, 8, None), ("inpaint", "win", [(242, 640, 332, 678)])],
    119: [("strokes", "win", PINK, 8, None)],
    121: [("match_width", "lose", "win")],
    135: [("undim", "win", 0.624, (152, 588, 479, 672)),
          ("fill", "win", [(480, 556, 625, 650)], (241, 241, 241)), ("fill", "win", [(625, 556, 627, 614)], (241, 241, 241)), ("fill", "win", [(472, 626, 480, 645)], (255, 255, 255))],
    137: [("crop", "lose", (0, 20, 954, 605))],
    152: [("strokes", "win", PINK, 8, None)],
    158: [("crop", "win", (33, 0, 542, 902)), ("crop", "lose", (39, 0, 547, 907))],  # VWO frames (purple V2 / orange V1)
    159: [("crop", "win", (21, 0, 530, 883)), ("crop", "lose", (10, 0, 524, 880))],  # VWO frames (purple V2 / pink V3)
    160: [("strokes", "win", (30, 150, 210), 8, (135, 625, 645, 1115), 60, 10)],
    162: [("fill", "win", [(1288, 726, 1348, 766)], (255, 255, 255))],
    164: [("strokes", "win", RED, 8, r, 40, 12) for r in [(405, 0, 795, 135), (215, 193, 1155, 260), (36, 690, 180, 735)]]
         + [("inpaint", "win", [(763, 105, 865, 151), (1126, 236, 1197, 278), (158, 708, 293, 752)]),
            ("crop", "both", (0, 9, 1197, 804))],  # purple frame edge (variation) / dark purple (control) on row 0-8
    166: [("strokes", "win", PINK, 8, None, 60, 14)],
    167: [("strokes", "win", RED, 8, None)],
    175: [("strokes", "win", RED, 8, (0, 30, 1214, 52))],
    168: [("strokes", "win", RED, 8, None), ("crop", "both", (2, 8, 482, 1017))],  # purple VWO frame edge on top
    176: [("strokes", "both", (200, 45, 40), 8, None), ("strokes", "win", (200, 45, 40), 8, (0, 300, 70, 400), 15)],
    178: [("strokes", "lose", (228, 36, 36), 8, None)],
    179: [("strokes", "win", (228, 60, 60), 8, (585, 365, 925, 460), 15),
          ("strokes", "lose", (228, 60, 60), 8, None)],
    180: [("strokes", "win", RED, 8, (730, 25, 915, 110))],
    181: [("trim_frame", "both", 90)],
    182: [("inpaint", "win", [(24, 121, 144, 161), (279, 137, 371, 181), (290, 174, 316, 196), (273, 189, 293, 205),
                              (482, 190, 603, 236), (536, 228, 559, 279), (482, 451, 505, 489), (418, 487, 533, 529)])],
    183: [("crop", "win", (150, 392, 2412, 1808)), ("crop", "lose", (150, 397, 2412, 1610))],  # inside the VWO frames
    189: [("match_width", "lose", "win")],
    190: [("match_width", "lose", "win")],
    198: [("strokes", "win", RED, 8, r, 25, 14) for r in
          [(14, 276, 62, 318), (193, 276, 241, 318), (20, 195, 72, 224), (0, 388, 37, 418)]],
    199: [("crop", "both", (30, 56, 486, 336)), ("strokes", "win", PINK, 8, None, 40)],
    205: [("crop", "both", (23, 119, 1498, 694)), ("strokes", "lose", PINK, 8, (1420, 265, 1475, 385), 40)],
    207: [("strokes", "win", RED, 8, None)],
    212: [("strokes", "win", RED, 4, (185, 130, 485, 276)), ("strokes", "win", RED, 4, (100, 335, 402, 447)),
          ("inpaint", "win", [(187, 178, 197, 256), (187, 178, 482, 188), (187, 246, 452, 256)])],
    213: [("strokes", "win", (252, 60, 60), 8, (20, 570, 1080, 930), 60, 12)],
    215: [("strokes", "win", PINK, 8, (90, 0, 1358, 198), 60, 14)],
    216: [("strokes", "win", RED, 8, (712, 704, 875, 853), 60, 14)],
    225: [("strokes", "win", (252, 12, 84), 8, r, 40, 12) for r in [(640, 131, 719, 189), (837, 139, 896, 193)]],
    226: [("strokes", "win", PINK, 8, (40, 1062, 1037, 1445), 50, 14), ("strokes", "win", PINK, 8, (975, 1100, 1037, 1135), 20, 14)],
    230: [("strokes", "win", RED, 8, None)],
    232: [("trim_frame", "both", 90)],
    235: [("strokes", "win", RED, 8, None)],
    237: [("strokes", "both", RED, 8, None)],
    239: [("strokes", "win", PINK, 8, (0, 0, 1903, 70), 60, 14), ("crop", "win", (16, 0, 1895, 892)),
          ("crop", "lose", (13, 9, 1898, 898))],  # pink box around the tested banner; orange / blue VWO frames
    240: [("strokes", "win", PINK, 8, (0, 0, 1838, 66), 60, 14), ("crop", "win", (8, 0, 1834, 876)),
          ("crop", "lose", (7, 6, 1833, 870))],  # pink box around the tested text strip; orange / blue VWO frames
    254: [("strokes", "win", PINK, 8, None)],
    258: [("crop", "both", (0, 55, 1200, 686)), ("inpaint", "win", [(35, 345, 150, 460)]),
          ("strokes", "win", RED, 10, (85, 455, 255, 562), 20, 12)],
    260: [("strokes", "win", RED, 8, None)],
    261: [("strokes", "win", RED, 8, None), ("crop", "win", (0, 0, 1204, 660))],
    277: [("blob", "lose", (250, 230, 20), 10, r) for r in [(1065, 305, 1125, 390), (1175, 385, 1228, 460)]],
}

# Pairs whose dataset label disagrees with a later statement by the source (kept as the dataset has it).
LABEL_NOTES: dict[int, str] = {
    62: "GoodUI leak #27 later added: 'the outcome of the experiment was flipped with black being the eventual "
        "implementation'. The dataset (and this set) keeps orange as the winner.",
}


def _sides(side: str):
    return ("win", "lose") if side == "both" else (side,)


def _box_mask(shape, region):
    m = np.zeros(shape[:2], np.uint8)
    if region is None:
        m[:] = 255
    else:
        x0, y0, x1, y1 = region
        m[y0:y1, x0:x1] = 255
    return m


def color_mask(im: np.ndarray, rgb, tol: int, region=None, thin: bool = True, minlen: int = 60,
               maxw: float = 9) -> np.ndarray:
    """Pixels of one annotation color. thin=True keeps only connected shapes that are long (>= minlen px) and sparse
    (< 35% of their bounding box): outlines, ellipses, arrows. Text, logos and filled page elements of the same color
    are left alone."""
    m = hue_mask(im, rgb, tol) & _box_mask(im.shape, region)
    if thin:
        joined = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))  # dashed / antialiased lines
        n, lab, st, _ = cv2.connectedComponentsWithStats(joined)
        keep = np.zeros(n, bool)
        for k in range(1, n):
            x, y, w, h, area = st[k]
            if max(w, h) < minlen:
                continue
            comp = (lab[y:y + h, x:x + w] == k).astype(np.uint8)
            cs, _ = cv2.findContours(comp, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
            half_perimeter = sum(cv2.arcLength(c, True) for c in cs) / 2
            keep[k] = area / max(half_perimeter, 1) <= maxw  # mean stroke width: lines, outlines, arrows
        m &= (keep[lab] * 255).astype(np.uint8)
    return cv2.dilate(m, np.ones((5, 5), np.uint8), iterations=2)


def frame_mask(im: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV).astype(int)
    h = hsv[..., 0]
    hue_ok = (h <= 14) | (h >= 155) | ((h >= 125) & (h <= 150)) | ((h >= 104) & (h <= 122))
    return hue_ok & (hsv[..., 1] >= 110) & (hsv[..., 2] >= 90)


def frame_trim_box(im: np.ndarray, maxd: int) -> tuple[int, int, int, int]:
    m = frame_mask(im)
    H, W = m.shape
    cut = {}
    for side, lines in (("top", (m[d] for d in range(maxd))), ("bottom", (m[H - 1 - d] for d in range(maxd))),
                        ("left", (m[:, d] for d in range(maxd))), ("right", (m[:, W - 1 - d] for d in range(maxd)))):
        last = -1
        for d, line in enumerate(lines):
            if line.mean() >= 0.5:  # a frame line runs along most of the edge; page content rarely does
                last = d
        cut[side] = last + 2 if last >= 0 else 0
    return cut["left"], cut["top"], W - cut["right"], H - cut["bottom"]


def hue_mask(im: np.ndarray, rgb, dh: int) -> np.ndarray:
    """Saturated, not-dark pixels whose hue is within dh (OpenCV hue units, 0-180) of rgb's hue."""
    hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV).astype(int)
    target = int(cv2.cvtColor(np.uint8([[rgb[::-1]]]), cv2.COLOR_BGR2HSV)[0, 0, 0])
    d = np.abs(hsv[..., 0] - target)
    d = np.minimum(d, 180 - d)
    return ((d <= dh) & (hsv[..., 1] >= 110) & (hsv[..., 2] >= 110)).astype(np.uint8) * 255


def apply_edits(imgs: dict, ops: list[tuple]) -> tuple[dict, list[str]]:
    notes = []
    for op in ops:
        kind, side = op[0], op[1]
        for lab in _sides(side):
            im = imgs[lab]
            if kind == "crop":
                x0, y0, x1, y1 = op[2]
                imgs[lab] = im[y0:y1, x0:x1].copy()
                notes.append(f"{lab}: crop to {op[2]}")
            elif kind == "inpaint":
                mask = np.zeros(im.shape[:2], np.uint8)
                for x0, y0, x1, y1 in op[2]:
                    mask[y0:y1, x0:x1] = 255
                imgs[lab] = cv2.inpaint(im, mask, 5, cv2.INPAINT_TELEA)
                notes.append(f"{lab}: inpaint {op[2]}")
            elif kind == "fill":
                im = im.copy()
                for x0, y0, x1, y1 in op[2]:
                    im[y0:y1, x0:x1] = op[3]
                imgs[lab] = im
                notes.append(f"{lab}: fill {op[2]} with {op[3]}")
            elif kind in ("strokes", "blob"):
                rgb, tol, region = op[2], op[3], op[4]
                minlen = op[5] if len(op) > 5 else 60
                maxw = op[6] if len(op) > 6 else 9
                mask = color_mask(im, rgb, tol, region, thin=kind == "strokes", minlen=minlen, maxw=maxw)
                imgs[lab] = cv2.inpaint(im, mask, 5, cv2.INPAINT_TELEA)
                notes.append(f"{lab}: remove {kind} rgb{tuple(rgb)} tol {tol} in {region or 'image'} "
                             f"({int((mask > 0).sum())} px)")
            elif kind == "trim_frame":
                box = frame_trim_box(im, op[2])
                x0, y0, x1, y1 = box
                imgs[lab] = im[y0:y1, x0:x1].copy()
                notes.append(f"{lab}: trim frame lines -> {box}")
            elif kind == "undim":
                factor, (x0, y0, x1, y1) = op[2], op[3]
                out = np.clip(im.astype(float) / factor, 0, 255).astype(np.uint8)
                out[y0:y1, x0:x1] = im[y0:y1, x0:x1]
                imgs[lab] = out
                notes.append(f"{lab}: undim /{factor} outside {op[3]}")
            elif kind == "match_width":
                ref = imgs[op[2]]
                w = ref.shape[1]
                h = int(round(im.shape[0] * w / im.shape[1]))
                imgs[lab] = cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA)
                notes.append(f"{lab}: resize to width {w} (match {op[2]})")
            else:
                raise ValueError(kind)
    return imgs, notes
