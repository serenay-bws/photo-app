"""Fit app-instellingen op voor/na-paren (*_b.png / *_a.png) in een map."""
import glob, json, sys
import numpy as np
from PIL import Image
from scipy.optimize import minimize
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parents[2]))
from app.edits import apply_edits, clean_params

folder, REG = sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 15
pairs = []
for f in sorted(glob.glob(f'{folder}/*_b.png')):
    b = Image.open(f).convert('RGB'); a = Image.open(f.replace('_b.png', '_a.png')).convert('RGB')
    s = 140 / max(b.size)
    size = (max(8, round(b.width * s)), max(8, round(b.height * s)))
    pairs.append((np.asarray(b.resize(size, Image.BOX)), np.asarray(a.resize(size, Image.BOX)).astype(np.float32)))
if not pairs:
    sys.exit('geen paren')

KEYS = ['exposure', 'contrast', 'highlights', 'shadows', 'blacks', 'saturation', 'temperature', 'tint',
        'fade', 'vignette', 'orange_sat', 'orange_lum', 'green_sat', 'blue_sat', 'yellow_sat',
        'orange_hue', 'green_hue', 'blue_hue']

def params(x):
    p = {k: v * 100 for k, v in zip(KEYS, x[:18])}
    for name, (a, b) in (('split_shadow', x[18:20]), ('split_highlight', x[20:22])):
        p[name] = float(np.hypot(a, b) * 100)
        p[name + '_hue'] = float(np.degrees(np.arctan2(b, a)) % 360)
    return clean_params(p)

def rmse_list(p):
    return [float(np.sqrt(np.mean((apply_edits(b, p).astype(np.float32) - a) ** 2))) for b, a in pairs]

def loss(x):
    p = params(x)
    err = np.mean([np.mean((apply_edits(b, p).astype(np.float32) - a) ** 2) for b, a in pairs])
    pen = 1000 * sum(max(0, -x[KEYS.index(k)]) for k in ('fade', 'vignette'))
    return err + pen + REG * float(np.sum(REGW * np.square(x)))

# kleurtinten mogen vrijer bewegen dan de basisregelaars
REGW = np.array([1.0] * 10 + [0.25] * 8 + [0.5] * 4)
x0 = np.zeros(22)
r = minimize(loss, x0, method='Powell', options={'maxiter': 5000, 'xtol': 2e-3, 'ftol': 1e-4})
p = params(r.x)
before = [float(np.sqrt(np.mean((b.astype(np.float32) - a) ** 2))) for b, a in pairs]
out = {k: round(v) for k, v in p.items() if abs(v) >= 1 or k.endswith('_hue')}
res = {'params': out, 'rmse_before': round(float(np.mean(before)), 1), 'rmse_after': round(float(np.mean(rmse_list(p))), 1), 'pairs': len(pairs)}
json.dump(res, open(f'{folder}/fit.json', 'w'))
print(json.dumps(res))
