# Memory, Task Routing and Learning Continuity

Study Agent uses memory to preserve learning continuity rather than presenting memory as a separate workspace.
The durable learning view centers on the current objective, confirmed points, unresolved gap and next action.
Task intent is decided once for a new turn using the server-owned contract: an explicit one-turn correction has highest priority, then clear text intent, then an active learning task, then a quick-answer default.
The ordinary composer does not require a permanent mode selector. A learner can open an on-demand task chip only when the automatic judgment needs correction.
Conversation and project context are loaded according to policy and task needs; compact summaries help control token cost without inventing mastery progress.
Retry and continuation restore the persisted task contract of the original turn instead of inheriting a new override.
Committed learning state, not message count or hint count, is the source of truth for what has actually been confirmed.
