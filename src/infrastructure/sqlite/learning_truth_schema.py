"""Global runtime schema migration for durable P2-D learning truth."""

from __future__ import annotations


LEARNING_TRUTH_MIGRATION_V17 = """
CREATE TABLE learning_topics (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    scope TEXT NOT NULL CHECK(scope IN ('project', 'general')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE learning_goals (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES learning_topics(id),
    objective TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active', 'blocked', 'completed', 'abandoned')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_learning_goals_topic_status
    ON learning_goals(topic_id, status, updated_at DESC);

CREATE TABLE learning_goal_prerequisites (
    goal_id TEXT NOT NULL REFERENCES learning_goals(id),
    prerequisite_goal_id TEXT NOT NULL REFERENCES learning_goals(id),
    PRIMARY KEY(goal_id, prerequisite_goal_id),
    CHECK(goal_id <> prerequisite_goal_id)
);

CREATE INDEX idx_learning_goal_prerequisites_prerequisite
    ON learning_goal_prerequisites(prerequisite_goal_id, goal_id);

CREATE TABLE learning_claims (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES learning_topics(id),
    scope TEXT NOT NULL CHECK(scope IN ('project', 'general')),
    claim_kind TEXT NOT NULL CHECK(
        claim_kind IN ('mechanism', 'boundary', 'invariant', 'decision_relevant_fact')
    ),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_learning_claims_topic_kind
    ON learning_claims(topic_id, claim_kind, created_at);

CREATE TABLE claim_revisions (
    id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL REFERENCES learning_claims(id),
    claim_text TEXT NOT NULL CHECK(length(trim(claim_text)) > 0),
    source_commit TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL CHECK(reason IN ('initial', 'revalidated', 'meaning_changed')),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_claim_revisions_claim_created
    ON claim_revisions(claim_id, created_at, id);

CREATE TRIGGER trg_claim_revisions_no_update
BEFORE UPDATE ON claim_revisions
BEGIN
    SELECT RAISE(ABORT, 'claim revisions are immutable');
END;

CREATE TRIGGER trg_claim_revisions_no_delete
BEFORE DELETE ON claim_revisions
BEGIN
    SELECT RAISE(ABORT, 'claim revisions are immutable');
END;

CREATE TABLE source_evidence (
    id TEXT PRIMARY KEY,
    repository TEXT NOT NULL CHECK(length(trim(repository)) > 0),
    commit_sha TEXT NOT NULL CHECK(length(trim(commit_sha)) > 0),
    tree_sha TEXT NOT NULL CHECK(length(trim(tree_sha)) > 0),
    path TEXT NOT NULL CHECK(length(trim(path)) > 0),
    file_sha TEXT NOT NULL CHECK(length(trim(file_sha)) > 0),
    symbol TEXT NOT NULL DEFAULT '',
    symbol_kind TEXT NOT NULL DEFAULT '',
    start_line INTEGER NOT NULL CHECK(start_line > 0),
    end_line INTEGER NOT NULL CHECK(end_line >= start_line),
    evidence_kind TEXT NOT NULL CHECK(length(trim(evidence_kind)) > 0),
    created_at TEXT NOT NULL,
    UNIQUE(
        repository, commit_sha, tree_sha, path, file_sha,
        symbol, symbol_kind, start_line, end_line, evidence_kind
    )
);

CREATE INDEX idx_source_evidence_repo_commit_path
    ON source_evidence(repository, commit_sha, path, start_line, end_line);

CREATE TRIGGER trg_source_evidence_no_update
BEFORE UPDATE ON source_evidence
BEGIN
    SELECT RAISE(ABORT, 'source evidence is immutable');
END;

CREATE TRIGGER trg_source_evidence_no_delete
BEFORE DELETE ON source_evidence
BEGIN
    SELECT RAISE(ABORT, 'source evidence is immutable');
END;

CREATE TABLE claim_revision_evidence (
    claim_revision_id TEXT NOT NULL REFERENCES claim_revisions(id),
    source_evidence_id TEXT NOT NULL REFERENCES source_evidence(id),
    role TEXT NOT NULL CHECK(
        role IN ('primary', 'supporting_corroborating', 'supporting_prerequisite')
    ),
    position INTEGER NOT NULL CHECK(position >= 0),
    PRIMARY KEY(claim_revision_id, source_evidence_id),
    UNIQUE(claim_revision_id, position)
);

CREATE UNIQUE INDEX idx_claim_revision_single_primary
    ON claim_revision_evidence(claim_revision_id)
    WHERE role = 'primary';

CREATE INDEX idx_claim_revision_evidence_source
    ON claim_revision_evidence(source_evidence_id, claim_revision_id);

CREATE TABLE understanding_evidence (
    id TEXT PRIMARY KEY,
    method TEXT NOT NULL CHECK(method IN ('explain', 'apply', 'practice')),
    prompt TEXT NOT NULL,
    user_response TEXT NOT NULL,
    verified_at TEXT NOT NULL
);

CREATE TABLE understanding_evidence_claims (
    understanding_evidence_id TEXT NOT NULL REFERENCES understanding_evidence(id),
    claim_revision_id TEXT NOT NULL REFERENCES claim_revisions(id),
    result TEXT NOT NULL CHECK(result IN ('pass', 'partial', 'fail')),
    PRIMARY KEY(understanding_evidence_id, claim_revision_id)
);

CREATE INDEX idx_understanding_evidence_claims_revision
    ON understanding_evidence_claims(claim_revision_id, understanding_evidence_id);

CREATE TABLE learning_hypotheses (
    id TEXT PRIMARY KEY,
    topic_id TEXT NOT NULL REFERENCES learning_topics(id),
    goal_id TEXT NOT NULL REFERENCES learning_goals(id),
    text TEXT NOT NULL CHECK(length(trim(text)) > 0),
    unresolved_reason TEXT NOT NULL CHECK(
        unresolved_reason IN (
            'missing_source',
            'ambiguous_owner',
            'insufficient_evidence',
            'external_dependency',
            'provider_unavailable'
        )
    ),
    resolved_by_claim_id TEXT REFERENCES learning_claims(id),
    created_at TEXT NOT NULL
);

CREATE INDEX idx_learning_hypotheses_goal_reason
    ON learning_hypotheses(goal_id, unresolved_reason, created_at);

CREATE TABLE next_steps (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES learning_goals(id),
    text TEXT NOT NULL CHECK(length(trim(text)) > 0),
    status TEXT NOT NULL CHECK(status IN ('active', 'completed', 'dismissed')),
    is_primary INTEGER NOT NULL DEFAULT 0 CHECK(is_primary IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX idx_next_steps_one_active_primary
    ON next_steps(goal_id)
    WHERE is_primary = 1 AND status = 'active';

CREATE INDEX idx_next_steps_goal_status
    ON next_steps(goal_id, status, updated_at DESC);

CREATE TABLE learner_misconceptions (
    id TEXT PRIMARY KEY,
    goal_id TEXT NOT NULL REFERENCES learning_goals(id),
    description TEXT NOT NULL CHECK(length(trim(description)) > 0),
    status TEXT NOT NULL CHECK(status IN ('suspected', 'confirmed', 'resolved')),
    occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK(occurrence_count >= 1),
    source_eval_ref TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE INDEX idx_learner_misconceptions_goal_status
    ON learner_misconceptions(goal_id, status, last_seen_at DESC);
"""
