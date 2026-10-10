"""Second-pass removal of GoodUI numbered markers that the benchmark repo's image_preprocess.process_image misses.

GoodUI marks the changed element on its variant screenshots with a purple speech-bubble circle holding a white digit
(fill about RGB 190,100,172, ~36 px at 1200 px page width, white rim). process_image only inpaints Hough circles whose
mean color is light purple, so a marker on a dark or busy background (e.g. pairs 7, 36, 53-55, 66, 98) survives.

Detection is deliberately narrow so page content is left alone: a blob of the marker fill color that is about square,
24-90 px, fills 55-90% of its box (a disc with a digit cut out), and has white (digit) pixels inside.
"""
from __future__ import annotations

import cv2
import numpy as np

FILL_BGR = np.array([172, 100, 190])


def find_markers(img: np.ndarray, tol: int = 40) -> list[tuple[int, int, int, int]]:
    m = (np.abs(img.astype(int) - FILL_BGR).max(2) < tol).astype(np.uint8)
    n, _, stats, _ = cv2.connectedComponentsWithStats(m)
    out = []
    for x, y, w, h, area in stats[1:]:
        if not (24 <= w <= 90 and 24 <= h <= 90 and 0.8 <= w / h <= 1.25):
            continue
        if not 0.55 <= area / (w * h) <= 0.9:
            continue
        inner = img[y + h // 4:y + 3 * h // 4, x + w // 4:x + 3 * w // 4]
        if (inner.min(2) > 215).mean() < 0.08:  # the white digit
            continue
        out.append((int(x), int(y), int(w), int(h)))
    return out


def remove_markers(img: np.ndarray) -> tuple[np.ndarray, list]:
    boxes = find_markers(img)
    if not boxes:
        return img, []
    mask = np.zeros(img.shape[:2], np.uint8)
    H, W = mask.shape
    for x, y, w, h in boxes:
        p = int(round(0.4 * max(w, h)))  # white rim + the bubble's square corner
        mask[max(0, y - p):min(H, y + h + p), max(0, x - p):min(W, x + w + p)] = 255
    return cv2.inpaint(img, mask, 5, cv2.INPAINT_TELEA), boxes


def find_ab_badges(img: np.ndarray) -> list[tuple[int, int, int, int]]:
    """abtest.design composites label each panel with a filled disc holding a white letter (A / B / C) near the top:
    gray for the control, blue for the variant, so its color gives the answer away. Returns disc boxes."""
    H, W = img.shape[:2]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(int)
    gray = (hsv[..., 1] < 25) & (hsv[..., 2] > 120) & (hsv[..., 2] < 200)
    blue = (np.abs(hsv[..., 0] - 108) < 10) & (hsv[..., 1] > 150) & (hsv[..., 2] > 180)
    out = []
    for m in (gray, blue):
        m = m.astype(np.uint8)
        m[int(0.2 * H):] = 0  # badges sit in the top band
        n, lab, st, _ = cv2.connectedComponentsWithStats(m)
        for k in range(1, n):
            x, y, w, h, area = st[k]
            if not (0.015 * W <= w <= 0.09 * W and 0.85 <= w / max(h, 1) <= 1.18):
                continue
            if not 0.5 <= area / (np.pi * w * h / 4) <= 1.02:  # a disc, minus the letter
                continue
            inner = img[y + h // 4:y + 3 * h // 4, x + w // 4:x + 3 * w // 4]
            if (inner.min(2) > 225).mean() < 0.05:  # the white letter
                continue
            out.append((int(x), int(y), int(w), int(h)))
    return out


def remove_ab_badges(img: np.ndarray) -> tuple[np.ndarray, list]:
    boxes = find_ab_badges(img)
    img = img.copy()
    for x, y, w, h in boxes:
        p = max(3, w // 12)
        x0, y0, x1, y1 = max(0, x - p), max(0, y - p), min(img.shape[1], x + w + p), min(img.shape[0], y + h + p)
        ring = np.concatenate([img[max(0, y0 - 4):y0, x0:x1].reshape(-1, 3), img[y1:y1 + 4, x0:x1].reshape(-1, 3),
                               img[y0:y1, max(0, x0 - 4):x0].reshape(-1, 3), img[y0:y1, x1:x1 + 4].reshape(-1, 3)])
        img[y0:y1, x0:x1] = np.median(ring, 0) if len(ring) else 245
    return img, boxes
