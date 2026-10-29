"""
chat/reasons.py — the error-wording map. One rule under test here: a failure
that is OURS must never be blamed on the model provider (the pause-save bug,
docs/MISSING.md 2026-10-27: a RequestDataTooBig 500 on the pause POST was
shown as "The model provider returned a server error").
"""
from django.test import SimpleTestCase

from chat.reasons import explain_ai_error


class ReasonMappingTests(SimpleTestCase):
    def test_a_pause_save_failure_is_ours_not_the_provider_s(self):
        worded = (
            "Couldn't hold this step for approval — the run's state could not "
            "be saved on the server. Nothing was approved or run; mention the "
            "persona again to retry."
        )
        out = explain_ai_error(worded)
        self.assertIn("hold this step for approval", out)
        self.assertNotIn("model provider", out)

    def test_the_pause_rule_wins_even_with_transport_noise_in_the_text(self):
        # A wrapped exception can carry the 500 alongside the worded message;
        # the pause rule sits before the 5xx rule, so ours still wins.
        noisy = ("Couldn't hold this step for approval — the run's state could "
                 "not be saved on the server (500 Internal Server Error)")
        out = explain_ai_error(noisy)
        self.assertIn("hold this step for approval", out)
        self.assertNotIn("model provider", out)

    def test_a_real_provider_5xx_still_names_the_provider(self):
        out = explain_ai_error("upstream answered 502 Bad Gateway")
        self.assertEqual(out, "The model provider returned a server error. Try again in a moment.")
