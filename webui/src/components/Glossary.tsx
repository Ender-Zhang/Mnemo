// A quick-reference drawer for Mnemo's core concepts, to lower the jargon barrier.

import { X } from "lucide-react";

const TERMS: Array<{ term: string; desc: string }> = [
  { term: "候选 Candidate", desc: "外部写入先变成候选记忆，不直接进入稳定记忆。" },
  { term: "Promote 晋升", desc: "把候选通过审核门写入稳定记忆页（新建或按主题合并）。" },
  { term: "稳定记忆页 Page", desc: "真正用于长期召回的记忆，按十维本体和主题组织。" },
  { term: "Tombstone 墓碑", desc: "标记某条记忆不可再用，但保留删除痕迹。" },
  { term: "Forget 私密擦除", desc: "抹掉内容本身（不可逆），保留不可复活的删除标记。" },
  { term: "Dream 维护", desc: "空闲期的有边界整理：晋升 / 去重 / 拒绝 / 建链，可选模型参与。" },
  { term: "Snapshot 快照", desc: "L1 记忆快照：trigger 路标 + 联想热点，默认注入提示词。" },
  { term: "L0 画像", desc: "从稳定记忆蒸馏的极简人格卡，每轮注入。" },
  { term: "Scope / UID", desc: "记忆归属（如 user:user_123）；当前是召回过滤，不是权限边界。" },
  { term: "Dimension 维度", desc: "十维本体：identity / preferences / goals / … 用于组织与路由。" },
  { term: "Provenance 溯源", desc: "事件 → 候选 → 稳定页的来源链，可在记忆详情查看。" },
  { term: "语义检索 Embeddings", desc: "可选向量召回；配独立 embeddings 端点后对同义改写更敏感。" }
];

export function GlossaryDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;
  return (
    <div className="drawer-layer" role="dialog" aria-modal="true" aria-label="术语帮助">
      <button className="drawer-backdrop" aria-label="关闭" onClick={onClose} />
      <aside className="memory-drawer">
        <div className="drawer-header">
          <div><h2>术语 / 帮助</h2><p>Mnemo 的核心概念，一句话速查。</p></div>
          <button className="ghost-button icon-only" onClick={onClose}><X size={16} /></button>
        </div>
        <div className="glossary-list">
          {TERMS.map((item) => (
            <div className="glossary-item" key={item.term}>
              <strong>{item.term}</strong>
              <p>{item.desc}</p>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
