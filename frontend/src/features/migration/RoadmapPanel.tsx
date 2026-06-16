import { ShieldCheck } from "lucide-react";

const roadmapItems = [
  "微信群和新闻已接入基础兼容流程。",
  "下一步补齐流式群聊、分阶段新闻、群聊搜索和记忆闭环。",
  "Streamlit 暂时保留为旧版业务闭环回归参考。"
];

export function RoadmapPanel() {
  return (
    <section className="panel compact" id="prd-roadmap">
      <div className="panel-header">
        <div>
          <h2>双版本对齐</h2>
          <span>按 PRD 保留能力边界</span>
        </div>
        <ShieldCheck size={18} />
      </div>
      <ul className="roadmap-list">
        {roadmapItems.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}
