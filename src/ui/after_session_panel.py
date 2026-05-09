"""课后更新面板 — 预览、确认写入、微信群反馈"""

import streamlit as st
from src.update_validator import validate_updates
from src.memory import read_memory_bundle
from src.mode_manager import (
    load_runtime_modes,
    is_memory_write_allowed,
    run_with_confirm_write,
)
from src.session_logger import set_after_session_status
from src.memory_writer import append_memory, write_current_focus
from src.wechat import generate_wechat_messages, append_wechat_messages
from src.after_session import apply_role_updates


def render_after_session_panel():
    if not st.session_state.after_session_updates:
        return

    st.divider()
    st.subheader("课后更新预览")

    updates = st.session_state.after_session_updates
    sections = [
        ("progress_update", "progress.md — 学习进度更新"),
        ("learner_profile_update", "learner_profile.md — 学习者档案更新"),
        ("current_focus_update", "current_focus.md — 当前焦点更新"),
        ("revision_notes_update", "revision_notes.md — 修订笔记"),
        ("session_archive_update", "session_archive.md — 本轮归档"),
    ]

    # Quality check
    quality_warnings = validate_updates(updates)
    if quality_warnings:
        with st.expander(
            f"[WARN] 质量检查发现 {len(quality_warnings)} 个问题", expanded=False
        ):
            for w in quality_warnings:
                st.caption(w)

    # Checkboxes per section
    if "update_checks" not in st.session_state:
        st.session_state.update_checks = {}
    for key, label in sections:
        st.session_state.update_checks[key] = st.checkbox(
            label, value=st.session_state.update_checks.get(key, True)
        )
        content = updates.get(key, "")
        with st.expander("查看内容", expanded=False):
            st.markdown(content)

    # current_focus diff
    if st.session_state.update_checks.get("current_focus_update"):
        old_cf = st.session_state.memory_bundle.get("current_focus.md", "")
        new_cf = updates.get("current_focus_update", "")
        if old_cf and not old_cf.startswith("[文件不存在") and new_cf:
            with st.expander("current_focus.md 对比（旧 → 新）", expanded=False):
                col1, col2 = st.columns(2)
                with col1:
                    st.caption("**旧内容**")
                    st.text(old_cf[:300] + ("..." if len(old_cf) > 300 else ""))
                with col2:
                    st.caption("**新内容**")
                    st.text(new_cf[:300] + ("..." if len(new_cf) > 300 else ""))

    # role_updates
    role_updates = updates.get("role_updates", {})
    if isinstance(role_updates, dict) and role_updates:
        with st.expander("角色动态记录更新", expanded=False):
            for role_id, obs in role_updates.items():
                if obs and obs != "本轮无需更新":
                    st.caption(f"**{role_id}**")
                    st.text(obs[:120])

    if st.button("确认写入长期记忆"):
        modes = load_runtime_modes()

        def _do_write():
            errors = []
            target_map = {
                "progress_update": ("progress", False),
                "learner_profile_update": ("learner_profile", True),
                "current_focus_update": (None, False),  # special: overwrite
                "revision_notes_update": ("revision_notes", False),
                "session_archive_update": ("session_archive", False),
            }
            for key, (target, learner_pending) in target_map.items():
                if not st.session_state.update_checks.get(key, True):
                    continue
                content = updates.get(key, "")
                if (
                    not content
                    or "（无对话记录）" in content
                    or "JSON 解析失败" in content
                ):
                    continue
                try:
                    if key == "current_focus_update":
                        write_current_focus(content)
                    else:
                        append_memory(target, content, learner_pending=learner_pending)
                except Exception as e:
                    errors.append(f"{key}: {e}")
            return errors

        if modes.safe_mode:
            st.warning("当前为安全模式，禁止写入长期记忆。")
        elif modes.memory_mode == "locked":
            st.warning("长期记忆已锁定，禁止写入。")
        else:
            with st.spinner("正在写入..."):
                errors = run_with_confirm_write(_do_write)
            modes = load_runtime_modes()
            st.session_state.runtime_modes = modes

            if errors:
                st.error("部分写入失败:\n" + "\n".join(errors))
            else:
                st.session_state.memory_bundle = read_memory_bundle()
                st.success("课后更新已写入。")
                with st.expander("写入验证", expanded=False):
                    mem = st.session_state.memory_bundle
                    for key, label in [
                        ("current_focus.md", "当前焦点"),
                        ("progress.md", "进度"),
                        ("summary.md", "核心摘要"),
                    ]:
                        content = mem.get(key, "")
                        if content and not content.startswith("[文件不存在"):
                            st.caption(f"**{label}**")
                            st.text(
                                content[:200] + ("..." if len(content) > 200 else "")
                            )

                set_after_session_status(st.session_state.session_id, "written")
                st.session_state.writes_confirmed = True

                # Apply role updates to dynamic records
                ru = updates.get("role_updates", {})
                if isinstance(ru, dict):
                    applied = apply_role_updates(ru)
                    if applied:
                        st.caption(f"角色动态记录已更新: {', '.join(applied)}")

                st.session_state.messages.append(
                    {
                        "role": "assistant",
                        "content": "本轮课后更新已写入。",
                    }
                )

    if st.session_state.writes_confirmed:
        st.selectbox(
            "群聊风格",
            options=["简短", "标准", "稍微有温度"],
            index=["简短", "标准", "稍微有温度"].index(st.session_state.wechat_style),
            key="wechat_style_select",
        )
        st.session_state.wechat_style = st.session_state.wechat_style_select

        if st.button("生成微信群反馈"):
            with st.spinner("正在生成群聊反馈..."):
                wechat = generate_wechat_messages(
                    session_messages=st.session_state.messages,
                    after_session_updates=st.session_state.after_session_updates or {},
                    memory_bundle=st.session_state.memory_bundle,
                    model_profile="flash",
                    style=st.session_state.wechat_style,
                    relationship_mode=st.session_state.interaction_mode,
                )
            if wechat:
                append_wechat_messages(wechat)
                st.session_state.wechat_messages = wechat
                from src.session_logger import set_wechat_status

                set_wechat_status(st.session_state.session_id, "generated")
                st.success("微信群反馈已生成。")
                st.session_state.after_session_updates = None
                st.session_state.writes_confirmed = False
