"""Opt-in web behaviour: use the shopper's fallback when no primary product qualifies."""

import unittest

from grocery_agent.interactive import InteractiveShoppingSession as S

RULE = "Buy the organic version of each item when available, otherwise the regular version."


def rules(constraints, fallback_quote=RULE):
    return {"constraints": constraints,
            "fallback": {"description": "regular marinara sauce", "search_query": "marinara sauce",
                         "evidence": [{"source": "instruction", "quote": fallback_quote}]}}


def tag(value, quote):
    return {"kind": "tag", "value": value, "evidence": [{"source": "instruction", "quote": quote}]}


class ConditionalPreferenceTagTests(unittest.TestCase):
    def test_organic_from_the_fallback_sentence_is_relaxed(self):
        organic = tag("organic", "Buy the organic version of each item when available")
        self.assertEqual(S._conditional_preference_tags(rules([organic])), [organic])

    def test_safety_tags_are_never_relaxed(self):
        gluten = tag("gluten_free", "Buy the organic version of each item when available")
        self.assertEqual(S._conditional_preference_tags(rules([gluten])), [])

    def test_organic_stated_elsewhere_stays_required(self):
        organic = tag("organic", "Everything must be organic")
        self.assertEqual(S._conditional_preference_tags(rules([organic])), [])

    def test_no_fallback_means_nothing_relaxed(self):
        organic = tag("organic", "organic")
        self.assertEqual(S._conditional_preference_tags({"constraints": [organic], "fallback": None}), [])


class OptInTests(unittest.TestCase):
    def test_disabled_by_default(self):
        session = S.__new__(S)
        session.fallback_when_primary_empty = False
        self.assertFalse(session._fallback_for_empty_primary(["r1"]))


if __name__ == "__main__":
    unittest.main()
