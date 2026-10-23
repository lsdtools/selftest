"""The pipeline package's execution role: the ``pipeline`` and ``run_log`` main views.

The views are the product's (``lsdtools.views``); GTK and the views are imported inside the factories.
"""
from __future__ import annotations

from lsdtools import Tool

tool = Tool("lsdtest/pipeline", label="Test Pipeline")


def _entities(host, entity):
    if entity is not None:
        return [entity]
    engine = getattr(host, "engine", None) if host is not None else None
    return [] if engine is None else engine.workspace.roots


@tool.main_view("pipeline", title="Pipeline", icon="lsd-node-symbolic", instance_policy="reusable",
                deliver_entity=lambda widget, entity: widget.set_entities([entity]))
def pipeline(host, *, entity=None, view_id):
    from lsdtools import views

    service = getattr(host, "service", None)
    package_scope = service("contributions") if callable(service) else None
    if package_scope is None:
        raise RuntimeError("Pipeline requires the host's project contribution scope")
    action_dispatch = service("dispatch_action") if callable(service) else None
    return views.pipeline_graph(_entities(host, entity), package_scope=package_scope,
                                action_dispatch=action_dispatch)


@tool.main_view("run_log", title="Run Log", icon="lsd-terminal-symbolic", instance_policy="single")
def run_log(host, *, entity=None, view_id):
    from lsdtools import views

    return views.run_log()


__all__ = ["tool"]
