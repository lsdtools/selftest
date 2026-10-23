"""The 3D viewer main view, built by the frontend context."""
from lsd_project import EntityRecord
from lsdtools.extend import Frontend, MainViewType


def _entity(value):
    return type(value) is EntityRecord


def viewer3d(context, *, entity=None, view_id):
    if entity is not None and not _entity(entity):
        raise TypeError("the Viewer requires a published entity")
    return context.create_viewer3d(entity=entity, view_id=view_id)


frontend = Frontend("lsdtest/viewer", (
    MainViewType("viewer3d", "3D Viewer", viewer3d, icon="lsd-graphics-symbolic", instance_policy="reusable",
                 binding_cardinality="many", accepts_entity=_entity),
))
