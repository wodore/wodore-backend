"""Tests for HutImageAssociation.import_score (import score stacking).

The image endpoints validate scores against 0–100: curated imports stack
upward from 90 (newest first) and must never run past 99 — an uncapped
"+= 1" loop re-minted >100 scores on large or repeated imports and 500'd
the endpoints all over again.
"""

from server.apps.huts.models import HutImageAssociation


class TestImportScore:
    def test_first_import_starts_at_upload_default(self):
        assert HutImageAssociation.import_score(None) == 90

    def test_stacks_upward_from_last_score(self):
        assert HutImageAssociation.import_score(90) == 91
        assert HutImageAssociation.import_score(95) == 96

    def test_treats_lower_scores_as_upload_floor(self):
        # A stray low previous score (e.g. a pin) stacks to the upload floor.
        assert HutImageAssociation.import_score(50) == 90
        assert HutImageAssociation.import_score(0) == 90

    def test_caps_at_score_max(self):
        assert HutImageAssociation.import_score(98) == 99
        assert HutImageAssociation.import_score(99) == 99
        # Legacy/pre-migration values cannot ratchet the stack past the cap.
        assert HutImageAssociation.import_score(1000) == 99

    def test_full_import_loop_stays_within_band(self):
        # Simulate a 15-photo import on a hut already topped at 99: every
        # score must stay inside 90..99.
        score = HutImageAssociation.import_score(99)
        scores = []
        for _ in range(15):
            scores.append(score)
            score = HutImageAssociation.import_score(score)
        assert scores == [99] * 15
