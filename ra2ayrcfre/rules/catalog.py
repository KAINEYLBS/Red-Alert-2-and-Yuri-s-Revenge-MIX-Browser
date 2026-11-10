"""Immutable rule metadata and context-based lookup."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType


class EditorSurface(str, Enum):
    """The editing interaction to which a rule may apply."""

    RAW_TEXT = "raw_text"
    STRUCTURED = "structured"


class RuleCategory(str, Enum):
    """Stable rule families, independent of the editor that presents them."""

    SYNTAX = "syntax"
    STRUCTURE = "structure"
    IDENTITY = "identity"
    CATALOG = "catalog"
    VALUE_CONSTRAINT = "value_constraint"
    CROSS_KEY_CONSTRAINT = "cross_key_constraint"
    LAYERING = "layering"


def _normalized_values(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        str(value).strip().casefold()
        for value in values
        if str(value).strip()
    )


def _exact_values(values: Iterable[str]) -> frozenset[str]:
    return frozenset(
        str(value).strip()
        for value in values
        if str(value).strip()
    )


@dataclass(frozen=True, slots=True)
class RuleScope:
    """Optional context restrictions; an empty set means any value."""

    editor_surfaces: frozenset[EditorSurface] = frozenset()
    document_formats: frozenset[str] = frozenset()
    file_keys: frozenset[str] = frozenset()
    game_variants: frozenset[str] = frozenset()
    section_names: frozenset[str] = frozenset()
    key_names: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        surfaces = frozenset(
            surface
            if isinstance(surface, EditorSurface)
            else EditorSurface(surface)
            for surface in self.editor_surfaces
        )
        object.__setattr__(self, "editor_surfaces", surfaces)
        for field_name in (
            "document_formats",
            "file_keys",
            "game_variants",
            "key_names",
        ):
            object.__setattr__(
                self,
                field_name,
                _normalized_values(getattr(self, field_name)),
            )
        object.__setattr__(self, "section_names", _exact_values(self.section_names))

    def matches(self, query: RuleQuery) -> bool:
        if (
            self.editor_surfaces
            and query.editor_surface not in self.editor_surfaces
        ):
            return False
        return (
            _context_matches(self.document_formats, query.document_format)
            and _context_matches(self.file_keys, query.file_key)
            and _context_matches(self.game_variants, query.game_variant)
            and _exact_context_matches(self.section_names, query.section_name)
            and _context_matches(self.key_names, query.key_name)
        )


def _context_matches(allowed: frozenset[str], actual: str) -> bool:
    return not allowed or bool(actual and actual.strip().casefold() in allowed)


def _exact_context_matches(allowed: frozenset[str], actual: str) -> bool:
    return not allowed or bool(actual and actual.strip() in allowed)


@dataclass(frozen=True, slots=True)
class RuleQuery:
    """Context used to select rules for a document or editing surface."""

    editor_surface: EditorSurface | None = None
    document_format: str = ""
    file_key: str = ""
    game_variant: str = ""
    section_name: str = ""
    key_name: str = ""
    categories: frozenset[RuleCategory] = frozenset()

    def __post_init__(self) -> None:
        if self.editor_surface is not None and not isinstance(
            self.editor_surface, EditorSurface
        ):
            object.__setattr__(
                self,
                "editor_surface",
                EditorSurface(self.editor_surface),
            )
        categories = frozenset(
            category
            if isinstance(category, RuleCategory)
            else RuleCategory(category)
            for category in self.categories
        )
        object.__setattr__(self, "categories", categories)


@dataclass(frozen=True, slots=True)
class RuleEvidence:
    evidence_id: str
    label: str
    url: str = ""
    applicability: str = ""


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    """One immutable rule record, including its basis and applicability."""

    rule_id: str
    category: RuleCategory
    rule: str
    authority: str
    impact: str = ""
    review_guidance: str = ""
    applicability: str = ""
    evidence: tuple[RuleEvidence, ...] = ()
    scope: RuleScope = RuleScope()

    def __post_init__(self) -> None:
        if not self.rule_id.strip():
            raise ValueError("Rule IDs must not be empty.")
        if not isinstance(self.category, RuleCategory):
            object.__setattr__(self, "category", RuleCategory(self.category))
        object.__setattr__(self, "evidence", tuple(self.evidence))


@dataclass(frozen=True, slots=True)
class RuleCatalog:
    """Read-only catalog with ID lookup and applicability queries."""

    definitions: tuple[RuleDefinition, ...]
    _by_id: Mapping[str, RuleDefinition] = field(
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        definitions = tuple(self.definitions)
        by_id = {definition.rule_id: definition for definition in definitions}
        if len(by_id) != len(definitions):
            raise ValueError("Rule IDs must be unique within a catalog.")
        object.__setattr__(self, "definitions", definitions)
        object.__setattr__(self, "_by_id", MappingProxyType(by_id))

    def get(self, rule_id: str) -> RuleDefinition | None:
        return self._by_id.get(rule_id)

    def select(self, query: RuleQuery) -> tuple[RuleDefinition, ...]:
        return tuple(
            definition
            for definition in self.definitions
            if (not query.categories or definition.category in query.categories)
            and definition.scope.matches(query)
        )

    def is_applicable(self, rule_id: str, query: RuleQuery) -> bool:
        definition = self.get(rule_id)
        return (
            definition is not None
            and (not query.categories or definition.category in query.categories)
            and definition.scope.matches(query)
        )
