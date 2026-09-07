from tasks import add


def test_add_returns_sum():
    assert add.run(4, 4) == 8


def test_add_accepts_negative_values():
    assert add.run(-3, 7) == 4


def test_add_preserves_fractional_values():
    assert add.run(0.25, 0.75) == 1.0
