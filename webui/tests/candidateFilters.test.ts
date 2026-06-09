import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { filterReviewableCandidates, isReviewableCandidate } from "../src/candidateFilters.ts";

describe("candidate review filtering", () => {
  it("keeps only draft and needs-review candidates in the review queue", () => {
    const candidates = [
      { id: "draft", status: "draft" },
      { id: "review", status: "needs_review:memory_safety" },
      { id: "promoted", status: "promoted" },
      { id: "rejected", status: "rejected:duplicate" },
      { id: "tombstoned", status: "tombstoned:manual" },
      { id: "missing" }
    ];

    assert.deepEqual(filterReviewableCandidates(candidates).map((candidate) => candidate.id), ["draft", "review"]);
  });

  it("treats status tokens case-insensitively and trims whitespace", () => {
    assert.equal(isReviewableCandidate({ status: " NEEDS_REVIEW:low_quality " }), true);
    assert.equal(isReviewableCandidate({ status: " PROMOTED " }), false);
  });
});
