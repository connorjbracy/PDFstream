import matplotlib.pyplot as plt
import numpy as np
import pytest

import pdfstream.pipeline.process as mod


@pytest.mark.parametrize(
    "img, bg_img, dk_img",
    [
        ("black_img", None, None),
        ("white_img", "white_img", None),
        ("white_img", None, "white_img"),
    ]
)
def test_reduce(test_data, img, bg_img, dk_img):
    npt = 64
    result = mod.reduce(
        test_data.get(img),
        ai=test_data['ai'],
        dk_img=test_data.get(dk_img, None),
        bg_img=test_data.get(bg_img, None),
        mask_setting="OFF",
        integ_setting={'npt': npt}
    )
    chi = result[0]
    assert np.array_equal(chi[1], np.zeros(npt))


@pytest.fixture
def kwargs(request, test_data):
    if request.param == "stream":
        return {}
    if request.param == "user":
        return {
            "user_ai": test_data["ai"],
            "user_config": {"composition": "Ni", "qmax": 20}
        }


@pytest.mark.parametrize(
    "kwargs",
    [
        "stream",
        "user"
    ],
    indirect=True
)
def test_process_img_to_pdf(kwargs, test_data):
    image, iq, sq, fq, gr = mod.process_img_to_pdf(
        test_data["Ni_img"],
        test_data["ai"],
        None,
        None,
        {"composition": "Ni"},
        **kwargs
    )
    # visualize
    plt.figure()
    image.plot()
    for arr in (iq, sq, fq, gr):
        plt.figure()
        arr.plot()
    plt.show(block=False)
    plt.close()


@pytest.mark.parametrize(
    "dct, expect",
    [
        ({}, None),
        ({"unit": "2th_deg"}, "twotheta"),
        pytest.param({"unit": "missing"}, None, marks=pytest.mark.xfail)
    ]
)
def test_get_dataformat(dct, expect):
    out = mod.get_dataformat(dct)
    assert out == expect
