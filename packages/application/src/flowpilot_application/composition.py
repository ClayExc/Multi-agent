from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .ports import ExecutionPort, TaskQueryUnitOfWorkFactory, UnitOfWorkFactory
from .services import CommandIntakeService, TaskQueryService


@dataclass(frozen=True, slots=True)
class CoreApplicationServices:
    """Framework-free application services used by the API composition root."""

    command_intake: CommandIntakeService
    task_query: TaskQueryService


def compose_core_application(
    *,
    command_unit_of_work: UnitOfWorkFactory,
    task_query_unit_of_work: TaskQueryUnitOfWorkFactory,
    execution: ExecutionPort,
    clock: Callable[[], datetime] | None = None,
) -> CoreApplicationServices:
    """Bind S2/S6 ports without importing their concrete adapters.

    Command acceptance and task projection deliberately receive separate unit
    of work capabilities.  A data adapter may implement both protocols, but
    the application layer never assumes that a command transaction can be
    reused as a read transaction.
    """

    return CoreApplicationServices(
        command_intake=CommandIntakeService(
            unit_of_work=command_unit_of_work,
            execution=execution,
            clock=clock,
        ),
        task_query=TaskQueryService(task_query_unit_of_work),
    )
