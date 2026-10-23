"""The pipeline package's frontend: the pipeline graph and the run log, from the frontend context."""
from lsd_project import EntityRecord
from lsdtools.extend import Frontend, MainViewType


def _entity(value):
    return type(value) is EntityRecord


def _deliver(widget, entity):
    if not _entity(entity):
        raise TypeError("the Pipeline requires an exact published entity")
    widget.set_entity_ids((entity.id,))


def pipeline(context, *, entity=None, view_id):
    if entity is not None and not _entity(entity):
        raise TypeError("the Pipeline requires an exact published entity")
    return context.create_pipeline(entity=entity, view_id=view_id)


def run_log(context, *, entity=None, view_id):
    if entity is not None and not _entity(entity):
        raise TypeError("the Run Log requires a published entity")
    return context.create_run_log(entity=entity, view_id=view_id)


frontend = Frontend("lsdtest/pipeline", (
    MainViewType("pipeline", "Pipeline", pipeline, icon="lsd-node-symbolic", instance_policy="reusable",
                 accepts_entity=_entity, deliver_entity=_deliver),
    MainViewType("run_log", "Run Log", run_log, icon="lsd-terminal-symbolic", instance_policy="single"),
))
