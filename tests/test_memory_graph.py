from __future__ import annotations

import tempfile
import unittest


class MemoryGraphTests(unittest.TestCase):
    def test_aggregates_dimensions_nodes_and_edges(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            client = MemoryClient(state_dir=tmp)
            page_ids = []
            for claim, dimension in [
                ("User writes Python and uses pytest.", "cognition"),
                ("User prefers concise progress updates.", "preferences"),
            ]:
                update = client.update(facts=[{"claim": claim, "dimension": dimension, "confidence": 0.9}], source="test")
                result = client.force_promote_candidate(update["memory_candidates"][0]["candidate_id"])
                page_ids.append(result["page_id"])

            client._store().add_memory_link(page_ids[0], page_ids[1], "related", weight=0.8)

            graph = client.memory_graph()
            dimensions = {row["dimension"]: row["count"] for row in graph["dimensions"]}
            self.assertEqual(dimensions.get("cognition"), 1)
            self.assertEqual(dimensions.get("preferences"), 1)
            self.assertEqual(len(graph["nodes"]), 2)
            self.assertEqual(len(graph["edges"]), 1)

            orphan_by_id = {node["id"]: node["orphan"] for node in graph["nodes"]}
            self.assertFalse(orphan_by_id[page_ids[0]])
            self.assertFalse(orphan_by_id[page_ids[1]])

    def test_empty_store_graph(self) -> None:
        from mnemo_memory import MemoryClient

        with tempfile.TemporaryDirectory() as tmp:
            graph = MemoryClient(state_dir=tmp).memory_graph()
            self.assertEqual(graph["nodes"], [])
            self.assertEqual(graph["edges"], [])
            self.assertEqual(graph["dimensions"], [])


if __name__ == "__main__":
    unittest.main()
