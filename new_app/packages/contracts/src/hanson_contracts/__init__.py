"""Shared contracts for the new architecture."""

from .sandbox import (
    ENGINE_API,
    OUTPUT_ROLES,
    DocumentRef,
    EngineRef,
    ExecutionDiagnostic,
    ExecutionManifest,
    ExecutionMetrics,
    ExecutionOutput,
    ExecutionRequest,
    ExecutionResult,
    ObjectInput,
    RecipeRef,
    ResourceLimits,
    RuntimeInfo,
    TableAssignment,
    TemplateRef,
)

__version__ = "0.0.0"

__all__ = [
    "ENGINE_API",
    "OUTPUT_ROLES",
    "DocumentRef",
    "EngineRef",
    "ExecutionDiagnostic",
    "ExecutionManifest",
    "ExecutionMetrics",
    "ExecutionOutput",
    "ExecutionRequest",
    "ExecutionResult",
    "ObjectInput",
    "RecipeRef",
    "ResourceLimits",
    "RuntimeInfo",
    "TableAssignment",
    "TemplateRef",
]
