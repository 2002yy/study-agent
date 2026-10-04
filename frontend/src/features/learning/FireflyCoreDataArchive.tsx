import { useState } from "react";

import { FireflyCharacterDataPanel } from "./FireflyCharacterDataPanel";
import {
  FIREFLY_ROUTE_SUPPORT_SCOPE,
  type FireflyCoreCharacterKey,
} from "./fireflyCharacterData";

const CORE_CHARACTER_ORDER: FireflyCoreCharacterKey[] = [
  "firefly",
  "dahlia",
  "fugue",
  "lingsha",
  "gallagher",
];

const CORE_CHARACTER_LABELS: Record<FireflyCoreCharacterKey, string> = {
  firefly: "流萤",
  dahlia: "大丽花",
  fugue: "忘归人",
  lingsha: "灵砂",
  gallagher: "加拉赫",
};

export function FireflyCoreDataArchive() {
  const [character, setCharacter] = useState<FireflyCoreCharacterKey>("firefly");

  return (
    <section className="firefly-interactive" id="firefly-core-data">
      <header>
        <h3>核心角色数值档案</h3>
        <p>五个核心角色按完整数据级展示：常用满级技能、秘技、削韧、能量、额外能力、1～6魂，以及当前页面实际比较的核心光锥精确叠影值。</p>
      </header>

      <div className="firefly-choice-row" aria-label="核心角色数值切换">
        {CORE_CHARACTER_ORDER.map((key) => (
          <button
            className={`firefly-choice${character === key ? " is-active" : ""}`}
            key={key}
            onClick={() => setCharacter(key)}
            type="button"
          >
            {CORE_CHARACTER_LABELS[key]}
          </button>
        ))}
      </div>

      <FireflyCharacterDataPanel character={character} />

      <details>
        <summary>配队辅助角色的数据边界</summary>
        <ul>
          {Object.entries(FIREFLY_ROUTE_SUPPORT_SCOPE).map(([name, scope]) => (
            <li key={name}><strong>{name}</strong>：{scope}</li>
          ))}
        </ul>
      </details>
    </section>
  );
}
