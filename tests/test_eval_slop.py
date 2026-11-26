"""M0 evaluation-harness contracts."""

import unittest

from tools.eval_slop import auc, split_groups, tpr_at_fpr


def row(text, label, group):
    return {"text": text, "label": label, "group": group}


ROWS = [
    row("she walked into the room and looked around slowly at everything", "neutral", "doc:p1"),
    row("he sat down at the table and opened the newspaper to the sports page", "neutral", "doc:p1"),
    row("the air was thick with a sense of dread and her stomach dropped", "bad", "doc:p2"),
    row("a shiver ran down her spine as the realization washed over her body", "bad", "doc:p2"),
]


class EvalTests(unittest.TestCase):
    def test_split_keeps_groups_whole(self):
        train, test = split_groups(ROWS, test_fraction=0.5, seed=1)
        train_groups = {item["group"] for item in train}
        test_groups = {item["group"] for item in test}
        self.assertFalse(train_groups & test_groups)
        self.assertEqual(len(train) + len(test), len(ROWS))

    def test_perfect_separation(self):
        tpr, fpr, threshold = tpr_at_fpr([90, 95], [10, 20])
        self.assertEqual(tpr, 1.0)
        self.assertEqual(fpr, 0.0)
        self.assertGreater(threshold, 20)

    def test_auc_perfect(self):
        self.assertEqual(auc([90, 95], [10, 20]), 1.0)

    def test_auc_chance(self):
        self.assertAlmostEqual(auc([50], [50]), 0.5)


if __name__ == "__main__":
    unittest.main()
