"""Typed errors for the content factory.

Rule: the pipeline never swallows or works around failures. Every failure is
one of these exceptions with a message that says what broke and how to fix it.
"""


class FactoryError(Exception):
    """Base class for every deliberate factory failure."""


class ConfigError(FactoryError):
    """config.json is missing, malformed, or violates the reference."""


class StageError(FactoryError):
    """A pipeline stage failed and downstream stages must not run.

    Attributes carry the stage id and the artifact directory that holds the
    full evidence (requests, responses, retries, reports).
    """

    def __init__(self, stage_id: str, message: str, artifacts_dir: str | None = None):
        self.stage_id = stage_id
        self.artifacts_dir = artifacts_dir
        super().__init__(f"[stage {stage_id}] {message}" + (f" (evidence: {artifacts_dir})" if artifacts_dir else ""))


class ModelCallError(StageError):
    """The inference server failed the call for a reason no retry can fix."""


class SchemaError(StageError):
    """Model output failed schema validation after all attempts."""


class SourceError(StageError):
    """A source PDF could not be fetched, parsed, or did not match the catalog."""


class LintError(StageError):
    """Generated code violated a hard lint rule."""


class BudgetError(StageError):
    """A page missed its performance budget after all fix rounds."""
