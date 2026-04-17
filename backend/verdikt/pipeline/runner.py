from dataclasses import dataclass, field


@dataclass
class PhaseResult:
    phase: str
    items_processed: int = 0


@dataclass
class PipelineResult:
    project_id: str
    phases: list[PhaseResult] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        return sum(p.items_processed for p in self.phases)


class PipelineRunner:
    """Sequential pipeline runner for Milestone 1.
    Prefect orchestration replaces this in Milestone 2.
    """

    def run(self, project_id: str) -> PipelineResult:
        result = PipelineResult(project_id=project_id)
        for phase_fn in (self._chunk, self._embed, self._cluster):
            result.phases.append(phase_fn(project_id))
        return result

    def _chunk(self, project_id: str) -> PhaseResult:
        raise NotImplementedError

    def _embed(self, project_id: str) -> PhaseResult:
        raise NotImplementedError

    def _cluster(self, project_id: str) -> PhaseResult:
        raise NotImplementedError
