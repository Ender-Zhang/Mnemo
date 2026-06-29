import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  humanizeDecisionReason,
  reasonFromStatus,
  dreamDecisionLog,
  qualityWeaknessReason,
  auditResultForItem
} from "../src/format.ts";

describe("decision reason humanizer", () => {
  it("maps terse codes to detailed Chinese explanations", () => {
    assert.match(humanizeDecisionReason("low_quality"), /质量分/);
    assert.match(humanizeDecisionReason("duplicate"), /重复/);
    assert.match(humanizeDecisionReason("below_confidence_threshold"), /置信度低于/);
    assert.match(humanizeDecisionReason("conflicts_with_active_memory"), /冲突/);
  });

  it("names the weak quality dimensions instead of a fixed generic string", () => {
    const signal = { weighted_avg: 0.51, scores: { specificity: 0.35, actionability: 0.3, persistence: 0.8, personalization: 0.7, verifiability: 0.9 } };
    const text = qualityWeaknessReason(signal);
    assert.match(text, /可执行度偏弱\(0\.30\)/);
    assert.match(text, /具体度偏弱\(0\.35\)/);
    assert.match(text, /总分 0\.51/);
    assert.equal(qualityWeaknessReason(null), "");
  });

  it("surfaces the weak dimensions on a low-quality candidate via its evidence", () => {
    const item = {
      id: "mem_1",
      type: "candidate" as const,
      status: "needs_review:low_quality",
      evidence: [{ kind: "memory_quality", weighted_avg: 0.51, scores: { specificity: 0.35, actionability: 0.3, persistence: 0.8 } }]
    };
    const audit = auditResultForItem(item);
    assert.equal(audit.label, "待复核");
    assert.match(audit.detail, /具体度偏弱|可执行度偏弱/);
  });

  it("explains auto-resolved conflicts (full-auto)", () => {
    assert.match(humanizeDecisionReason("conflict_resolved:keep_new"), /用新记忆替换/);
    assert.match(humanizeDecisionReason("conflict_resolved:keep_old"), /保留旧记忆/);
    assert.match(humanizeDecisionReason("conflict_resolved:keep_both"), /同时保留/);
    assert.match(humanizeDecisionReason("conflict_resolved:merge"), /模型消解/);
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
