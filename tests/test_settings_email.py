"""Admin-email settings parsing must survive every configuration shape.

Regression: the old comprehension produced ``[[""]]`` for an empty
``DJANGO_ADMIN_EMAILS`` (CI), and ``[entry[1] ...]`` consumers raised
IndexError the first time the feedbacks email path ran without the env
var — which the throttling test now does (5 successful POSTs).
"""

from server.settings.components.email import parse_admin_emails


class TestParseAdminEmails:
    def test_empty_string_yields_no_entries(self):
        assert parse_admin_emails("") == []

    def test_empty_comma_slots_are_dropped(self):
        assert parse_admin_emails(",,") == []

    def test_name_address_pair(self):
        assert parse_admin_emails("Tobias <tb@wodore.com>") == [
            ["Tobias", "tb@wodore.com"]
        ]

    def test_bare_address_gets_empty_name(self):
        assert parse_admin_emails("ops@wodore.com") == [["", "ops@wodore.com"]]

    def test_multiple_entries_mixed_shapes(self):
        assert parse_admin_emails("Tobias <tb@wodore.com>,,ops@wodore.com") == [
            ["Tobias", "tb@wodore.com"],
            ["", "ops@wodore.com"],
        ]

    def test_surrounding_whitespace_is_stripped(self):
        assert parse_admin_emails("  Tobias  <tb@wodore.com> ") == [
            ["Tobias", "tb@wodore.com"]
        ]
