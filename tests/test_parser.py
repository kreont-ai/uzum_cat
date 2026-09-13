from uzum_cat.parser import find_product_list, flatten_product


def test_find_product_list_in_graphql_style_response():
    payload = {
        "data": {
            "makeSearch": {
                "items": [
                    {"id": "1", "title": "Товар 1", "price": 100, "rating": 4.5, "reviews": 10},
                    {"id": "2", "title": "Товар 2", "price": 200, "rating": 4.8, "reviews": 3},
                ]
            }
        }
    }
    items = find_product_list(payload)
    assert items is not None
    assert len(items) == 2
    assert items[0]["title"] == "Товар 1"


def test_find_product_list_in_edges_node_style_response():
    payload = {
        "data": {
            "category": {
                "products": {
                    "edges": [
                        {"node": {"productId": "a", "name": "X", "sellPrice": 10, "shopTitle": "Shop A"}},
                        {"node": {"productId": "b", "name": "Y", "sellPrice": 20, "shopTitle": "Shop B"}},
                        {"node": {"productId": "c", "name": "Z", "sellPrice": 30, "shopTitle": "Shop C"}},
                    ]
                }
            }
        }
    }
    items = find_product_list(payload)
    assert items is not None
    nodes = [it["node"] for it in items]
    assert {n["productId"] for n in nodes} == {"a", "b", "c"}


def test_find_product_list_returns_none_when_nothing_matches():
    payload = {"data": {"errors": [{"message": "boom"}], "meta": {"page": 1}}}
    assert find_product_list(payload) is None


def test_flatten_product_picks_known_aliases():
    item = {"productId": "42", "name": "Товар", "sellPrice": 99.5, "shopTitle": "Shop"}
    flat = flatten_product(item)
    assert flat == {
        "product_id": "42",
        "title": "Товар",
        "price": 99.5,
        "shop": "Shop",
    }


def test_flatten_product_empty_when_no_known_keys():
    assert flatten_product({"foo": "bar"}) == {}
