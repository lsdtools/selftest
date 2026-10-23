"""The workspace's frontend: the entity tree, the inspector and the tables, from the frontend context."""
from lsd_project import ConfigurableRecord, EntityRecord
from lsdtools.extend import Frontend, MainViewType, SidebarViewContribution

from lsd_desktop_ui.project_tree import project_explorer_tree_extension, project_tree_extension

PACKAGE = "lsdtest/workspace"


def _entity(value):
    return type(value) is EntityRecord


def _subject(value):
    return type(value) in (EntityRecord, ConfigurableRecord)


def _deliver_to_inspector(target, value):
    if not _subject(value):
        raise TypeError("the Inspector requires an exact published record")
    target.load_record(value)


def entity_tree(context):
    return context.create_project_tree()


def inspector(context, *, entity=None, view_id):
    return context.create_common_inspector(entity=entity, view_id=view_id)


def completed_table(context, *, entity=None, view_id, product_id):
    if not _entity(entity):
        raise TypeError("the Table requires an exact published entity")
    return context.create_table(entity=entity, view_id=view_id, product_id=product_id)


def dataset_table(context, *, entity=None, view_id, product_id):
    if not _entity(entity):
        raise TypeError("the dataset Table requires an exact published entity")
    return context.create_dataset_table(entity=entity, view_id=view_id, product_id=product_id)


frontend = Frontend(PACKAGE, (
    SidebarViewContribution("entity_tree", "Entity Tree", entity_tree, icon="lsd-tree-symbolic",
                            position=0, primary=True, default_open=True),
    MainViewType("inspector", "Inspector", inspector, icon="lsd-settings-symbolic",
                 instance_policy="reusable", default_open=False, layout_hint="floating",
                 accepts_entity=_subject, deliver_entity=_deliver_to_inspector),
    MainViewType("completed_table", "Table", completed_table, icon="lsd-table-symbolic",
                 instance_policy="per_entity", accepts_entity=_entity, route_parameter="product_id"),
    MainViewType("dataset_table", "Data Table", dataset_table, icon="lsd-table-symbolic",
                 instance_policy="per_entity", accepts_entity=_entity, route_parameter="product_id"),
    project_tree_extension(PACKAGE),
    project_explorer_tree_extension(PACKAGE),
))
