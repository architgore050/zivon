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
        super().__init__(
            f"[stage {stage_id}] {message}"
            + (f" (evidence: {artifacts_dir})" if artifacts_dir else "")
        )


class ModelCallError(StageError):
    """The inference server failed the call for a reason no retry can fix."""


class SchemaError(StageError):
    """Model output failed schema validation after all attempts."""


class SourceError(StageError):
    """A source PDF could not be fetched, parsed, or did not match the catalog."""


class MissingArtifactError(FactoryError):
    """A stage needs an upstream stage output that no run has.

    Raised by RunContext.load_stage_output when neither the current run nor
    any previous run under runs/ holds the artifact - i.e. the requested
    --stages subset starts too late. The message says which stages to run.
    """


class LintError(StageError):
    """Generated code violated a hard lint rule."""


class BudgetError(StageError):
    """A page missed its performance budget.

    fixable=True: the failing page is topic-local (page.js / page.css), so
    stage 08-fixloop can attempt model repairs. fixable=False: nothing
    downstream can fix it (e.g. the hand-maintained landing page) - a human
    must. report carries the harness measurements for the orchestrator.
    """

    def __init__(
        self,
        stage_id: str,
        message: str,
        artifacts_dir: str | None = None,
        *,
        fixable: bool = True,
        report: dict | None = None,
    ):
        super().__init__(stage_id, message, artifacts_dir)
        self.fixable = fixable
        self.report = report
