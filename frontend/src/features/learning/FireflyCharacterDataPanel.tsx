import {
  FIREFLY_CORE_CHARACTER_DATA,
  type FireflyCoreCharacterKey,
} from "./fireflyCharacterData";
import { FIREFLY_CORE_LIGHT_CONES } from "./fireflyCoreLightCones";

export function FireflyCharacterDataPanel({ character }: { character: FireflyCoreCharacterKey }) {
  const data = FIREFLY_CORE_CHARACTER_DATA[character];
  const lightCones = FIREFLY_CORE_LIGHT_CONES[character];

  return (
    <section className="firefly-character-data" aria-label={`${data.name}完整数据`}>
      <h4>{data.name} · 常用满级数值</h4>
      {data.versionNote ? <div className="firefly-note">{data.versionNote}</div> : null}
      <div className="firefly-table-wrap">
        <table className="firefly-table">
          <thead>
            <tr>
              <th>技能</th>
              <th>等级</th>
              <th>倍率 / 治疗 / 核心值</th>
              <th>能量</th>
              <th>削韧</th>
              <th>持续 / 额外效果</th>
            </tr>
          </thead>
          <tbody>
            {data.skills.map((skill) => (
              <tr key={`${data.name}-${skill.name}`}>
                <td>{skill.name}</td>
                <td>{skill.rank}</td>
                <td>{skill.value}</td>
                <td>{skill.energy}</td>
                <td>{skill.toughness}</td>
                <td>{skill.extra}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <details>
        <summary>额外能力 / 行迹</summary>
        <ul>{data.traces.map((trace) => <li key={trace}>{trace}</li>)}</ul>
      </details>

      <details>
        <summary>1～6魂精确效果</summary>
        <ol>{data.eidolons.map((eidolon) => <li key={eidolon}>{eidolon}</li>)}</ol>
      </details>

      <details>
        <summary>核心光锥精确数值</summary>
        <div className="firefly-table-wrap">
          <table className="firefly-table">
            <thead>
              <tr>
                <th>光锥</th>
                <th>叠影</th>
                <th>精确效果</th>
                <th>当前体系备注</th>
              </tr>
            </thead>
            <tbody>
              {lightCones.map((cone) => (
                <tr key={`${data.name}-${cone.name}-${cone.superimposition}`}>
                  <td>{cone.name}</td>
                  <td>{cone.superimposition}</td>
                  <td>{cone.effect}</td>
                  <td>{cone.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <div className="firefly-note">
        默认展示实际常用满级：普攻Lv.6、战技/终结技/天赋Lv.10；3魂/5魂提高技能等级上限，但不在正文默认铺开Lv.1～15成长表。光锥只列当前页面实际用于比较或推荐的核心选项，不扩展成全光锥图鉴。
      </div>
    </section>
  );
}
