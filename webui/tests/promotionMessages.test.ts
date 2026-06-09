import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { promotionReviewMessage } from "../src/promotionMessages.ts";

describe("promotion review messages", () => {
  it("explains when promotion creates a new stable memory page", () => {
    assert.equal(
      promotionReviewMessage({
        decision: "promoted",
        status: "promoted",
        page_action: "created",
        page: { title: "preferences: 沟通风格" }
      }),
      "审核通过：已新建稳定记忆页「preferences: 沟通风格」"
    );
  });

  it("explains when promotion merges into an existing stable memory page", () => {
    assert.equal(
      promotionReviewMessage({
        decision: "promoted",
        status: "promoted",
        page_action: "merged",
        page: { title: "preferences: 沟通风格" }
      }),
      "审核通过：已合并到已有稳定记忆页「preferences: 沟通风格」；稳定记忆页数量不会增加"
    );
  });
});
