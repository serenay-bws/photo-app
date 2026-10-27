import numpy as np

from app.edits import apply_edits, clean_params, default_params, effective_params
from app.presets import BUILTIN, presets_by_id
from tests.helpers import sample_image


def arr():
    return np.asarray(sample_image(300, 200))


def test_identity_returns_same_pixels():
    a = arr()
    assert np.array_equal(apply_edits(a, default_params()), a)


def test_exposure_brightens_and_darkens():
    a = arr()
    brighter = apply_edits(a, {"exposure": 50})
    darker = apply_edits(a, {"exposure": -50})
    assert brighter.mean() > a.mean() + 10
    assert darker.mean() < a.mean() - 10


def test_saturation_minus_100_is_greyscale():
    out = apply_edits(arr(), {"saturation": -100}).astype(int)
    assert np.abs(out[..., 0] - out[..., 1]).max() <= 1
    assert np.abs(out[..., 1] - out[..., 2]).max() <= 1


def test_temperature_shifts_red_blue():
    a = arr().astype(float)
    warm = apply_edits(arr(), {"temperature": 60}).astype(float)
    assert (warm[..., 0] - warm[..., 2]).mean() > (a[..., 0] - a[..., 2]).mean() + 5


def test_vignette_darkens_corners_not_center():
    flat = np.full((200, 300, 3), 160, np.uint8)
    out = apply_edits(flat, {"vignette": 100})
    assert out[100, 150].mean() > 155
    assert out[0, 0].mean() < 90


def test_fade_lifts_blacks():
    black = np.zeros((50, 50, 3), np.uint8)
    assert apply_edits(black, {"fade": 100}).mean() > 40


def test_grain_adds_noise_but_keeps_mean():
    flat = np.full((400, 400, 3), 128, np.uint8)
    out = apply_edits(flat, {"grain": 100}).astype(float)
    assert out.std() > 3
    assert abs(out.mean() - 128) < 2


def test_strips_are_seamless_with_sharpening():
    """Grote foto's worden in stroken bewerkt; er mogen geen naden ontstaan."""
    a = np.asarray(sample_image(600, 700))
    p = clean_params({"sharpness": 100, "contrast": 20})
    import app.edits as ed

    full = ed.apply_edits(a, p)
    old = ed.STRIP_ROWS
    try:
        ed.STRIP_ROWS = 50
        strips = ed.apply_edits(a, p)
    finally:
        ed.STRIP_ROWS = old
    assert np.array_equal(full, strips)


def test_all_builtin_presets_render():
    a = arr()
    for preset in BUILTIN:
        out = apply_edits(a, preset["params"])
        assert out.shape == a.shape and out.dtype == np.uint8
        assert not np.array_equal(out, a), preset["name"]


def test_moody_dark_is_darker_and_less_saturated():
    a = arr().astype(float)
    p = presets_by_id()["moody-dark"]["params"]
    out = apply_edits(arr(), p).astype(float)
    sat = lambda x: (x.max(2) - x.min(2)).mean()
    assert out.mean() < a.mean()
    assert sat(out) < sat(a)


def test_effective_params_strength_and_adjust():
    presets = presets_by_id()
    base = presets["moody-dark"]["params"]
    half = effective_params({"preset": "moody-dark", "strength": 50, "adjust": {"exposure": 10}}, presets)
    assert half["exposure"] == base["exposure"] * 0.5 + 10
    assert half["vignette"] == base["vignette"] * 0.5
    none = effective_params({"preset": None, "adjust": {"contrast": 999}}, presets)
    assert none["contrast"] == 100  # begrensd
    assert effective_params(None, presets) == default_params()


def test_clean_params_rejects_garbage():
    p = clean_params({"exposure": "abc", "grain": float("nan"), "tint": -500, "unknown": 3})
    assert p["exposure"] == 0 and p["grain"] == 0 and p["tint"] == -100
    assert "unknown" not in p


def test_hsl_only_touches_its_color_range():
    img = np.zeros((10, 30, 3), np.uint8)
    img[:, :10] = (200, 130, 80)    # huid / oranje
    img[:, 10:20] = (60, 160, 70)   # groen
    img[:, 20:] = (128, 128, 128)   # grijs
    out = apply_edits(img, {"orange_lum": -60, "green_sat": -100}).astype(int)
    assert out[:, :10].mean() < img[:, :10].mean() - 15          # huid donkerder
    g = out[0, 15]
    assert max(g) - min(g) < (160 - 60) * 0.5                    # groen veel minder kleurrijk
    assert np.abs(out[:, 20:] - 128).max() <= 1                  # grijs onaangetast


def test_dither_avoids_banding_but_keeps_values():
    grad = np.tile(np.linspace(0, 255, 300).astype(np.uint8), (50, 1))[..., None].repeat(3, 2)
    out = apply_edits(grad, {"exposure": -100}).astype(float)
    # zonder dithering zou elke kolom één vaste waarde hebben (harde streepjes)
    assert out[:, 150, 0].std() > 0
    assert out[:, 150, 0].max() - out[:, 150, 0].min() <= 1
