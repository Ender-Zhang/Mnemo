import tempfile
import unittest


class PromotionPageActionTests(unittest.TestCase):
    def test_promotion_reports_created_then_merged_page_action(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)

            first = client.update(
                facts=[
                    {
                        "claim": "User prefers concise progress updates in implementation reports.",
                        "dimension": "preferences",
                        "confidence": 0.92,
                    }
                ],
                source="unit-test",
            )
            first_candidate_id = first["memory_candidates"][0]["candidate_id"]

            first_promotion = client.promote_candidate(first_candidate_id)

            self.assertEqual(first_promotion["decision"], "promoted")
            self.assertEqual(first_promotion["page_action"], "created")

            second = client.update(
                facts=[
                    {
                        "claim": "User prefers direct status reports while coding.",
                        "dimension": "preferences",
                        "confidence": 0.91,
                    }
                ],
                source="unit-test",
            )
            second_candidate_id = second["memory_candidates"][0]["candidate_id"]

            second_promotion = client.promote_candidate(second_candidate_id)

            self.assertEqual(second_promotion["decision"], "promoted")
            self.assertEqual(second_promotion["page_action"], "merged")
            self.assertEqual(second_promotion["page_id"], first_promotion["page_id"])
            self.assertEqual(client.list(kind="page", status="active", limit=10)["count"], 1)


if __name__ == "__main__":
    unittest.main()
