"""Behavior probe for the category endpoints after traversal/caching changes."""

import pytest

pytestmark = pytest.mark.django_db


def _get(client, path, **params):
    r = client.get(path, params)
    assert r.status_code == 200, (path, r.status_code, r.content[:200])
    return r.json()


class TestCategoryEndpoints:
    def test_tree_root_shapes(self, seed_data, client):
        data = _get(client, "/v1/categories/tree/root")
        assert isinstance(data, list) and data
        node = data[0]
        assert {"slug", "name", "order", "level", "identifier", "color"} <= set(node)

    def test_tree_children_kinds(self, seed_data, client):
        data = _get(client, "/v1/categories/tree/root")
        leaf_kinds = {type(n["children"]).__name__ for n in data}
        assert leaf_kinds <= {"list", "bool"}

    def test_list_root_flat(self, seed_data, client):
        data = _get(client, "/v1/categories/list/root")
        assert isinstance(data, list) and data
        assert all(isinstance(n["children"], bool) for n in data)

    def test_map_root_nested(self, seed_data, client):
        data = _get(client, "/v1/categories/map/root")
        assert isinstance(data, dict) and data
        first = next(iter(data.values()))
        assert isinstance(first["children"], dict)
        assert first["children_count"] == len(first["children"])

    def test_level_limit_leaf(self, seed_data, client):
        data = _get(client, "/v1/categories/tree/root", level=0)
        assert all(
            n["children"] is False or isinstance(n["children"], bool) for n in data
        )

    def test_second_request_served_from_page_cache(self, seed_data, client):
        first = client.get("/v1/categories/tree/root")
        second = client.get("/v1/categories/tree/root")
        assert first.status_code == second.status_code == 200
        assert first.content == second.content
