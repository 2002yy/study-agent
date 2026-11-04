import { useEffect, useState, useSyncExternalStore } from "react";
import { deleteLocalSkill, importLocalSkill, listLocalSkills, setLocalSkillEnabled, type LocalSkill } from "../../api";
import { getPendingSkillSelection, setPendingSkillSelection, subscribeSkillSelection } from "./skillSelection";
import "./SkillPanel.css";

export function SkillPanel() {
  const [skills, setSkills] = useState<LocalSkill[]>([]);
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const selected = useSyncExternalStore(subscribeSkillSelection, getPendingSkillSelection);
  useEffect(() => {
    let active = true;
    listLocalSkills().then(result => { if (active) {
      setSkills(result.skills);
      setPendingSkillSelection(getPendingSkillSelection().filter(id => result.skills.some(skill => skill.id === id && skill.enabled)));
    } })
      .catch(() => { if (active) setError("Skill 列表读取失败，请重新打开设置重试。"); })
      .finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, []);
  const perform = async (action: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await action(); } catch { setError("操作失败，请检查 SKILL.md 内容或稍后重试；现有选择仍保留。"); }
    finally { setBusy(false); }
  };
  const toggleSelection = (skill: LocalSkill) => {
    const next = selected.includes(skill.id) ? selected.filter(id => id !== skill.id) : [...selected, skill.id];
    if (next.length > 3) { setError("下条消息最多使用三个 Skill。"); return; }
    if (skills.filter(item => next.includes(item.id)).reduce((sum, item) => sum + item.content.length, 0) > 24000) {
      setError("已选 Skill 正文合计不能超过 24000 字符。"); return;
    }
    setError(""); setPendingSkillSelection(next);
  };
  return <section className="side-section skill-panel" aria-label="本地 Skill" style={{ minWidth: 0, overflowWrap: "anywhere" }}>
    <h3>本地 Skill</h3>
    <p>导入纯文本 SKILL.md，安装后默认停用。启用后可为下一条单聊消息选择，最多三个；发送后自动清空选择。</p>
    <label className="field-row">粘贴 SKILL.md
      <textarea rows={7} value={content} onChange={event => setContent(event.target.value)}
        style={{ width: "100%", boxSizing: "border-box", fontSize: 14 }} />
    </label>
    <label className="field-row">上传 SKILL.md
      <input type="file" accept=".md,text/markdown,text/plain" disabled={busy} onChange={event => {
        const file = event.target.files?.[0];
        if (!file) return;
        if (file.size > 100000) { setError("文件过大，请导入不超过 20000 字符的文本。"); return; }
        void file.text().then(text => { setContent(text); setError(""); }).catch(() => setError("文件读取失败。"));
      }} />
    </label>
    <button type="button" disabled={busy || !content.trim() || content.length > 20000} onClick={() => void perform(async () => {
      const installed = await importLocalSkill(content);
      setSkills(current => [...current.filter(item => item.id !== installed.id), installed]); setContent("");
    })}>安装 Skill</button>
    {content.length > 20000 ? <p role="alert">正文不能超过 20000 字符。</p> : null}
    <p role="status">下条消息已选 {selected.length}/3：{skills.filter(skill => selected.includes(skill.id)).map(skill => skill.name).join("、") || "无"}</p>
    {error ? <p role="alert">{error}</p> : null}
    {!skills.length ? <p>尚未安装本地 Skill。</p> : null}
    {skills.map(skill => <article key={skill.id} aria-label={skill.name}>
      <h4>{skill.name}</h4><p>{skill.description}</p>
      <label><input type="checkbox" checked={skill.enabled} disabled={busy} onChange={() => void perform(async () => {
        const updated = await setLocalSkillEnabled(skill.id, !skill.enabled);
        setSkills(current => current.map(item => item.id === skill.id ? updated : item));
        if (!updated.enabled) setPendingSkillSelection(getPendingSkillSelection().filter(id => id !== skill.id));
      })} />启用 {skill.name}</label>
      <button type="button" aria-pressed={selected.includes(skill.id)} disabled={busy || !skill.enabled}
        onClick={() => toggleSelection(skill)}>{selected.includes(skill.id) ? "取消下条消息使用" : "下条消息使用"} {skill.name}</button>
      <button type="button" disabled={busy} onClick={() => void perform(async () => {
        await deleteLocalSkill(skill.id); setSkills(current => current.filter(item => item.id !== skill.id));
        setPendingSkillSelection(getPendingSkillSelection().filter(id => id !== skill.id));
      })}>删除 {skill.name}</button>
      <details><summary>查看 SKILL.md：{skill.name}</summary><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", fontSize: 14 }}>{skill.content}</pre></details>
    </article>)}
  </section>;
}
