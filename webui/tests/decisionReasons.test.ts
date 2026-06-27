import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  humanizeDecisionReason,
  reasonFromStatus,
  dreamDecisionLog
} from "../src/format.ts";

describe("decision reason humanizer", () => {
  it("maps terse codes to detailed Chinese explanations", () => {
    assert.match(humanizeDecisionReason("low_quality"), /质量分过低/);
    assert.match(humanizeDecisionReason("duplicate"), /重复/);
    assert.match(humanizeDecisionReason("below_confidence_threshold"), /置信度低于/);
    assert.match(humanizeDecisionReason("conflicts_with_active_memory"), /冲突/);
  });

  it("translates the backend promote-gate phrasing with confidence numbers", () => {
    const reason = "passed quality and confidence gates; confidence 0.82 >= 0.70; created a stable page (preferences)";
    const text = humanizeDecisionReason(reason);
    assert.match(text, /新建稳定记忆/);
    assert.match(text, /0\.82/);
    assert.match(text, /0\.70/);
  });

  it("keeps unknown free-text reasons as-is and empty input empty", () => {
    assert.equal(humanizeDecisionReason(""), "");
    assert.equal(humanizeDecisionReason("某个自定义原因"), "某个自定义原因");
  });

  it("expands a status suffix into a detailed reason", () => {
    assert.match(reasonFromStatus("rejected:duplicate"), /重复/);
    assert.match(reasonFromStatus("needs_review:conflict"), /冲突/);
    assert.equal(reasonFromStatus("active"), "");
  });
});

describe("dream decision log", () => {
  it("builds a per-candidate promote/reject log with humanized reasons", () => {
    const status = {
      latest: {
        execution: {
          review_results: [
            { candidate_id: "memcand_1", decision: "promoted", status: "promoted", reason: "passed quality and confidence gates; confidence 0.9 >= 0.7; created a stable page", page_title: "preferences: tone" },
            { candidate_id: "memcand_2", decision: "rejected", status: "rejected:duplicate", reason: "duplicate" }
          ]
        }
      }
    } as never;

    const log = dreamDecisionLog(status);
    assert.equal(log.length, 2);
    assert.equal(log[0].tone, "good");
    assert.match(log[0].reason, /稳定记忆/);
    assert.equal(log[1].tone, "bad");
    assert.match(log[1].reason, /重复/);
  });

  it("returns an empty log when there is no dream status", () => {
    assert.deepEqual(dreamDecisionLog(null), []);
  });
});
