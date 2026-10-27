"""Vind voor/na-panelen in een productafbeelding (links voor, rechts na).

Werkwijze: de twee panelen tonen dezelfde foto met andere kleuren. We zoeken de
horizontale verschuiving waarbij de randen (gradiënten) van links en rechts het best
overeenkomen, en bepalen daarna welke rijen/kolommen echt overeenkomen (de foto zelf).
Uitvoer: (voor, na) als PIL-afbeeldingen, of None.
"""

import sys

import numpy as np
from PIL import Image


def edges(g):
    gx = np.zeros_like(g)
    gy = np.zeros_like(g)
    gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
    gy[1:-1] = g[2:] - g[:-2]
    return np.hypot(gx, gy)


def find_pair(img, min_dx=0.30, max_dx=0.62):
    img = img.convert("RGB")
    W, H = img.size
    g = np.asarray(img.convert("L"), dtype=np.float32) / 255
    e = edges(g)
    # normaliseren per rij voorkomt dat kleurverschillen tellen
    best = (-1, 0, 0)
    for dx in range(int(W * min_dx), int(W * max_dx), 2):
        a = e[:, : W - dx]
        b = e[:, dx:]
        num = (a * b).sum()
        den = np.sqrt((a * a).sum() * (b * b).sum()) + 1e-9
        c = num / den
        if c > best[0]:
            best = (c, dx, 0)
    c, dx, _ = best
    for d in range(dx - 3, dx + 4):  # fijn
        for dy in range(-4, 5):
            a = e[max(0, -dy) : H - max(0, dy), : W - d]
            b = e[max(0, dy) : H - max(0, -dy), d:]
            cc = (a * b).sum() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-9)
            if cc > best[0]:
                best = (cc, d, dy)
    c, dx, dy = best
    a = e[max(0, -dy) : H - max(0, dy), : W - dx]
    b = e[max(0, dy) : H - max(0, -dy), dx:]
    # lokale overeenkomst per blok van 16 px
    bs = 16
    hh, ww = (a.shape[0] // bs) * bs, (a.shape[1] // bs) * bs
    A = a[:hh, :ww].reshape(hh // bs, bs, ww // bs, bs)
    B = b[:hh, :ww].reshape(hh // bs, bs, ww // bs, bs)
    num = (A * B).sum(axis=(1, 3))
    den = np.sqrt((A * A).sum(axis=(1, 3)) * (B * B).sum(axis=(1, 3))) + 1e-9
    energy = np.minimum((A * A).sum(axis=(1, 3)), (B * B).sum(axis=(1, 3)))
    match = (num / den > 0.6) & (energy > 1e-3)
    # grootste rechthoek met veel overeenkomst: rijen/kolommen met >25% match
    rows = match.mean(axis=1) > 0.25
    cols = match.mean(axis=0) > 0.25

    def longest(mask):
        best, cur, start, bstart = 0, 0, 0, 0
        for i, m in enumerate(mask):
            if m:
                if cur == 0:
                    start = i
                cur += 1
                if cur > best:
                    best, bstart = cur, start
            else:
                cur = 0
        return bstart, bstart + best

    r0, r1 = longest(rows)
    c0, c1 = longest(cols)
    if (r1 - r0) * bs < H * 0.25 or (c1 - c0) * bs < W * 0.15:
        return None
    # randje eraf (afgeronde hoeken, kaders)
    y0, y1 = r0 * bs + 8, r1 * bs - 8
    x0, x1 = c0 * bs + 8, min(c1 * bs, dx) - 8
    ys = max(0, -dy)
    # labels ("before"/"after") staan vaak bovenaan het paneel: bovenste 12% eraf
    y0 = y0 + int((y1 - y0) * 0.12)
    before = img.crop((x0, y0 + ys, x1, y1 + ys))
    after = img.crop((x0 + dx, y0 + ys + dy, x1 + dx, y1 + ys + dy))
    # controle: binnen de uitsnede moeten de randen echt overeenkomen (geen collage)
    eb = edges(np.asarray(before.convert("L"), dtype=np.float32) / 255)
    ea = edges(np.asarray(after.convert("L"), dtype=np.float32) / 255)
    crop_corr = float((eb * ea).sum() / (np.sqrt((eb * eb).sum() * (ea * ea).sum()) + 1e-9))
    aspect = before.height / max(1, before.width)
    if crop_corr < 0.65 or not (1.0 <= aspect <= 2.6):
        return None
    return before, after, crop_corr


if __name__ == "__main__":
    for f in sys.argv[1:]:
        r = find_pair(Image.open(f))
        if r is None:
            print(f, "geen paar")
            continue
        b, a, c = r
        print(f, "paar", b.size, round(c, 3))
        b.save(f.replace(".jpg", "_b.png"))
        a.save(f.replace(".jpg", "_a.png"))
