def validate_updates(updates: dict[str, str]) -> list[str]:
    warnings = []

    for key, label in [
        ("progress_update", "进度更新"),
        ("learner_profile_update", "学习者档案"),
        ("current_focus_update", "当前焦点"),
        ("revision_notes_update", "修订笔记"),
        ("session_archive_update", "归档"),
    ]:
        content = updates.get(key, "")

        if not content or "（无对话记录）" in content or "JSON 解析失败" in content:
            continue

        if len(content) > 500:
            warnings.append(f"{label} 过长 ({len(content)} 字符)，建议精简")

        emotion_keywords = [
            "焦虑",
            "烦躁",
            "担心",
            "害怕",
            "压抑",
            "沮丧",
            "急躁",
            "没耐心",
            "不自信",
            "自卑",
            "无聊",
            "抗拒",
        ]
        matched = [kw for kw in emotion_keywords if kw in content]
        if matched:
            warnings.append(f"{label} 包含情绪推断: {matched}")

        sensitive_keywords = [
            "年龄",
            "性别",
            "住址",
            "身份证",
            "手机号",
            "工资",
            "收入",
            "公司",
            "学校名",
        ]
        matched = [kw for kw in sensitive_keywords if kw in content]
        if matched:
            warnings.append(f"{label} 疑似含敏感信息: {matched}")

        overclaim = [
            "v0.6",
            "v0.7",
            "已上线",
            "已部署",
        ]
        matched = [kw for kw in overclaim if kw in content]
        if matched:
            warnings.append(f"{label} 写入了未完成功能: {matched}")

    return warnings
