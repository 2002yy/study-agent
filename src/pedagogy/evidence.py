from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from src.pedagogy.types import PedagogyTurnPlan


@dataclass(frozen=True)
class DisclosedEvidence:
    context: str = ""
    private_context: str = ""
    policy: str = "none"
    units: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class EvidenceUnit:
    source_id: str
    type: str
    content: str
    citation: str
    disclosure_role: str
    reliability: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _local_retrieval_constraint(status: str) -> EvidenceUnit | None:
    if status in {"not_found", "index_missing"}:
        content = (
            "Local material was requested, but no supporting local evidence was found. "
            "Do not imply that the user's materials support a factual answer."
        )
    elif status == "insufficient":
        content = (
            "Related local material was found, but evidence is insufficient for the specific "
            "question. Do not answer the unsupported fact as if it were grounded in the user's materials."
        )
    elif status == "uncertain":
        content = (
            "Local material is topically related, but support is uncertain. Treat it as context only; "
            "do not convert partial similarity into a confident source-backed claim."
        )
    else:
        return None
    return EvidenceUnit(
        source_id="local-retrieval-constraint",
        type="retrieval_constraint",
        content=content,
        citation="local:none",
        disclosure_role="constraint",
        reliability=1.0,
    )


def build_evidence_units(
    *,
    rag: dict[str, Any],
    web_context: str,
) -> list[EvidenceUnit]:
    units: list[EvidenceUnit] = []
    constraint = _local_retrieval_constraint(str(rag.get("status") or ""))
    if constraint is not None:
        units.append(constraint)
    for index, result in enumerate(rag.get("results") or (), start=1):
        if not isinstance(result, dict):
            continue
        chunk = result.get("chunk") or {}
        if not isinstance(chunk, dict):
            continue
        content = str(chunk.get("text", "")).strip()
        if not content:
            continue
        source_path = str(chunk.get("source_path", "local"))
        start = chunk.get("start_line", "")
        end = chunk.get("end_line", "")
        units.append(
            EvidenceUnit(
                source_id=str(chunk.get("chunk_id") or f"rag-{index}"),
                type="document_chunk",
                content=content,
                citation=f"{source_path}:L{start}-L{end}",
                disclosure_role="supporting_material",
                reliability=0.9,
            )
        )
    for index, block in enumerate(
        part.strip() for part in web_context.split("\n\n") if part.strip()
    ):
        units.append(
            EvidenceUnit(
                source_id=f"web-{index + 1}",
                type="search_excerpt" if len(block.splitlines()) <= 3 else "article_excerpt",
                content=block,
                citation=f"web:{index + 1}",
                disclosure_role="external_fact",
                reliability=0.72,
            )
        )
    return units


def _format_units(units: list[EvidenceUnit], heading: str) -> str:
    if not units:
        return ""
    lines = [heading]
    for unit in units:
        lines.append(
            f"[{unit.source_id}] ({unit.type}; {unit.citation})\n{unit.content}"
        )
    return "\n\n".join(lines)


class EvidenceDisclosurePolicy:
    def select(
        self,
        *,
        units: list[EvidenceUnit] | None = None,
        plan: PedagogyTurnPlan,
        context: str = "",
    ) -> DisclosedEvidence:
        if units is None:
            units = (
                [
                    EvidenceUnit(
                        source_id="legacy-context",
                        type="document_chunk",
                        content=context.strip(),
                        citation="legacy",
                        disclosure_role="supporting_material",
                        reliability=0.5,
                    )
                ]
                if context.strip()
                else []
            )
        if not units:
            return DisclosedEvidence()
        private_context = _format_units(
            units,
            "[Private library evidence: use for planning accuracy; do not reveal unless selected below]",
        )
        selectable = [unit for unit in units if unit.disclosure_role != "constraint"]
        if not selectable:
            return DisclosedEvidence(
                private_context=private_context,
                policy="private_constraints_only",
            )
        if plan.disclosure_level >= 5:
            selected = selectable
            policy = "full"
        elif plan.knowledge_kind in {"empirical", "conventional"}:
            selected = [
                unit for unit in selectable
                if unit.disclosure_role in {"external_fact", "necessary_fact"}
            ] or selectable[:1]
            policy = "necessary_external_fact"
        elif plan.disclosure_level >= 3:
            selected = [
                unit for unit in selectable
                if unit.type in {"definition", "search_excerpt", "document_chunk"}
            ][:2]
            policy = "bounded_units"
        elif plan.disclosure_level >= 2:
            selected = selectable[:1]
            policy = "single_evidence_unit"
        else:
            selected = []
            policy = "withheld_derivable_answer"
        return DisclosedEvidence(
            context=_format_units(selected, "[Evidence allowed for user disclosure]"),
            private_context=private_context,
            policy=policy,
            units=tuple(unit.to_dict() for unit in selected),
        )
