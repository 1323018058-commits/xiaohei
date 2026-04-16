from app.services import bid_service


def test_target_price_defaults_to_three_times_current_price():
    assert bid_service.resolve_target_price(528, None) == 1584
    assert bid_service.resolve_target_price(528, 0) == 1584
    assert bid_service.resolve_target_price(0, None) == 0


def test_target_price_preserves_manual_value():
    assert bid_service.resolve_target_price(528, 999) == 999
