from uzum_cat.product_detail import extract_orders_amount


def test_extract_orders_amount_finds_value():
    html = 'shortDescription:a,ordersAmount:20,isBlockedOrArchived:b,adultCategory:j'
    assert extract_orders_amount(html) == 20


def test_extract_orders_amount_missing_returns_none():
    html = "<html><body>no such field here</body></html>"
    assert extract_orders_amount(html) is None


def test_extract_orders_amount_zero():
    html = "foo,ordersAmount:0,bar"
    assert extract_orders_amount(html) == 0
