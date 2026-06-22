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

// The ten-dimension ontology used to organize and route memories.
// Labels mirror the backend (mnemo_memory/memory/learning.py).
const DIMENSIONS: Array<{ key: string; label: string; desc: string }> = [
  { key: "identity", label: "个人资料", desc: "你是谁：身份、角色等长期不变的基本信息。" },
  { key: "cognition", label: "知识与技能", desc: "你会什么：掌握的知识、技能、专长。" },
  { key: "values", label: "价值观", desc: "你在乎什么：原则、信念、判断取向。" },
  { key: "goals", label: "目标", desc: "你想达成什么：长短期目标与意图。" },
  { key: "preferences", label: "服务偏好", desc: "你希望被怎样对待：风格、格式、协作方式。" },
  { key: "relationships", label: "关系网络", desc: "你和谁有关：人、团队、组织的关系。" },
  { key: "context", label: "当前情境", desc: "你此刻所处的情况：在做的项目、环境、时区（会变化）。" },
  { key: "history", label: "经历历史", desc: "你过去发生过什么：已成事实的经历。" },
  { key: "patterns", label: "行为模式", desc: "你习惯怎么做：重复出现的行为与节奏。" },
  { key: "boundaries", label: "边界", desc: "不能碰的红线：禁忌、限制、硬约束。" }
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
        <h3 className="glossary-subhead">十维本体 · 维度对照</h3>
        <p className="glossary-subnote">每条记忆按下面十个维度归类与路由（事件流 / 维度筛选里看到的标签）。</p>
        <div className="glossary-list">
          {DIMENSIONS.map((item) => (
            <div className="glossary-item" key={item.key}>
              <strong>{item.key} · {item.label}</strong>
              <p>{item.desc}</p>
            </div>
          ))}
        </div>
      </aside>
    </div>
  );
}
