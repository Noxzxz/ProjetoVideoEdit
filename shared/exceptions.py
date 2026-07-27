class PipelineError(Exception):
    pass


class VideoNotFoundError(PipelineError):
    pass


class AudioExtractionError(PipelineError):
    pass


class TranscriptionError(PipelineError):
    pass


class CleaningError(PipelineError):
    pass


class ContentGenerationError(PipelineError):
    pass


class TimelineValidationError(PipelineError):
    pass


class EditingError(PipelineError):
    pass


class ExportError(PipelineError):
    pass


class ExternalServiceError(PipelineError):
    pass


class PreflightError(PipelineError):
    pass
