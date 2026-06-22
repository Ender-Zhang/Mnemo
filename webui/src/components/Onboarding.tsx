// First-run checklist shown when the memory store is empty, to guide setup.

import { ArrowRight, Sparkles, X } from "lucide-react";

export function OnboardingChecklist(props: {
  hasProvider: boolean;
  onConfigure: () => void;
  onAddMemory: () => void;
  onRunDream: () => void;
  onPreview: () => void;
  onDismiss: () => void;
}) {
  const steps = [
    { label: "配置模型 / Embeddings（可选）", done: props.hasProvider, action: props.onConfigure, cta: "去设置" },
    { label: "写入第一条记忆", done: false, action: props.onAddMemory, cta: "保存记忆" },
    { label: "运行一次 Dream 整理", done: false, action: props.onRunDream, cta: "去维护" },
    { label: "在「记忆预览」看 agent 会拿到什么", done: false, action: props.onPreview, cta: "去预览" }
  ];
  return (
    <section className="panel onboarding">
      <div className="panel-header compact">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Sparkles size={18} />
          <h2>开始使用 Mnemo</h2>
        </div>
        <button className="ghost-button icon-only" onClick={props.onDismiss} title="不再显示"><X size={15} /></button>
      </div>
      <p className="onboarding-intro">还没有记忆。按下面几步把记忆系统跑起来：</p>
      <ol className="onboarding-steps">
        {steps.map((step, index) => (
          <li className={step.done ? "done" : ""} key={step.label}>
            <span className="onboarding-index">{step.done ? "✓" : index + 1}</span>
            <span className="onboarding-label">{step.label}</span>
            <button className="ghost-button" onClick={step.action}>{step.cta}<ArrowRight size={14} /></button>
          </li>
        ))}
      </ol>
    </section>
  );
}
