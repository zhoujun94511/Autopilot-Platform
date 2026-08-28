"""Design application services."""
from .access import ensure_project_access, ensure_project_write, resolve_list_scope
from .automation_sync import apply_result_json_to_logical_cases
__all__ = ["ensure_project_access", "ensure_project_write", "resolve_list_scope", "apply_result_json_to_logical_cases"]
