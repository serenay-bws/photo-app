import numpy as np
from PIL import Image

from app.edits import apply_edits, clean_params
from app.match import describe, fingerprint, match_look
from tests.helpers import sample_image


def test_match_look_recovers_dark_desaturated_look():
    src = sample_image(240, 180, seed=1)
    target = clean_params({"exposure": -60, "saturation": -50, "temperature": 30})
    reference = Image.fromarray(apply_edits(np.asarray(sample_image(240, 180, seed=2)), target))
    params, before, after = match_look(src, reference, max_evals=400)
    assert after < before * 0.3
    assert params["exposure"] < -20
    assert params["saturation"] < -15
    assert params["temperature"] > 5
    assert "donkerder" in describe(params)


def test_fingerprint_detects_skin_tones():
    img = np.zeros((40, 40, 3), np.uint8)
    img[:] = (205, 140, 105)
    fp = fingerprint(img)
    assert "orange" in fp and "green" not in fp
