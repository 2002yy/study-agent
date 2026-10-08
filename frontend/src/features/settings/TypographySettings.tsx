import { useId } from "react";
import { TYPOGRAPHY_OPTIONS, setTypographyPreference, useTypographyPreference } from "./typographyPreference";

export function TypographySettings() {
  const preset = useTypographyPreference();
  const name = useId();
  return (
    <section className="side-section typography-settings" aria-label="阅读外观">
      <fieldset>
        <legend className="section-title">阅读字体</legend>
        <p className="field-hint">选择后立即生效，记住这台设备的显示偏好。</p>
        <div className="typography-options">
          {TYPOGRAPHY_OPTIONS.map(option => <label key={option.value} className={preset === option.value ? "is-selected" : ""}>
            <input type="radio" name={name} value={option.value} checked={preset === option.value}
              onChange={() => setTypographyPreference(option.value)}/>
            <span><strong>{option.label}</strong><small>{option.description}</small></span>
          </label>)}
        </div>
        <div className="typography-preview" aria-label="字体预览"><strong>把问题读清楚</strong><p>读一段资料，留下一个清楚的问题。</p></div>
      </fieldset>
    </section>
  );
}
