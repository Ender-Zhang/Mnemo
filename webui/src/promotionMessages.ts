export type PromotionReviewResult = {
  decision?: string;
  status?: string;
  reason?: string;
  page_id?: string;
  page_action?: "created" | "merged" | string;
  page?: {
    title?: string;
  };
};

export function promotionReviewMessage(result: PromotionReviewResult) {
  const decision = result.decision || "";
  const reason = result.reason ? `：${result.reason}` : "";
  if (decision === "promoted" || result.status === "promoted") {
    const pageTitle = result.page?.title ? `「${result.page.title}」` : "";
    if (result.page_action === "created") {
      return `审核通过：已新建稳定记忆页${pageTitle}`;
    }
    if (result.page_action === "merged") {
      return `审核通过：已合并到已有稳定记忆页${pageTitle}；稳定记忆页数量不会增加`;
    }
    return "审核通过：候选已提升为稳定记忆";
  }
  if (decision === "rejected" || result.status?.startsWith("rejected")) {
    return `审核拒绝：候选未进入稳定记忆${reason}`;
  }
  if (decision === "conflict" || result.status?.includes("conflict")) {
    return `审核发现冲突：请人工确认${reason}`;
  }
  if (decision === "skipped") {
    return `审核暂不提升${reason}`;
  }
  return `审核完成：${result.status || "未提升"}`;
}
