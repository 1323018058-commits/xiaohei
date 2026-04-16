from app.services import bid_service


def test_syncable_offer_status_filters_disabled_and_stock_at_takealot():
    assert bid_service.is_bid_product_syncable_status("Buyable") is True
    assert bid_service.is_bid_product_syncable_status("") is True
    assert bid_service.is_bid_product_syncable_status(None) is True
    assert bid_service.is_bid_product_syncable_status("Not Buyable") is False
    assert bid_service.is_bid_product_syncable_status(" Disabled by Seller ") is False
    assert bid_service.is_bid_product_syncable_status("Disabled by Takealot") is False
    assert bid_service.is_bid_product_syncable_status("Offers with Stock at Takealot") is False
