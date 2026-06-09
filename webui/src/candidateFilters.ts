export type CandidateStatusItem = {
  status?: string;
};

export function isReviewableCandidate(candidate: CandidateStatusItem) {
  const status = String(candidate.status || "").trim().toLowerCase();
  return status === "draft" || status.startsWith("needs_review");
}

export function filterReviewableCandidates<T extends CandidateStatusItem>(candidates: T[]) {
  return candidates.filter(isReviewableCandidate);
}
