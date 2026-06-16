import { ShieldCheck } from "lucide-react";

const roadmapItems = [
  "微信群、新闻讨论和课后总结仍需要 PRD 中的新增 API 才能完整迁移。",
  "React 当前先补齐单人学习设置、路由检查、RAG 参数和会话状态。",
  "Streamlit 暂时保留为业务闭环回归参考。"
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
