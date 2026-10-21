# Configure native Paperless roles, never a separate retention engine.
# Executed by manage.py shell while lifecycle authority excludes other writers.
import json
import os
from pathlib import Path

from django.contrib.auth.models import Group, Permission, User
from django.db import transaction
from documents.models import CustomField, Workflow, WorkflowAction, WorkflowTrigger
from rest_framework.authtoken.models import Token

GROUP = "bartl-users"
WORKFLOWS = (
    ("Records intake ownership", 0, "intake", None),
    ("Captured mail ownership", 1, "capture", "capture-*"),
)
DAILY = {
    "view_document", "change_document", "view_tag", "view_correspondent",
    "view_documenttype", "view_customfield", "view_uisettings",
    "add_uisettings", "view_savedview",
}
INTAKE = {
    "add_document", "view_document", "view_tag", "view_correspondent",
    "view_documenttype", "view_customfield", "view_paperlesstask",
}
ROLES = {"intake": INTAKE, "capture": INTAKE | {"change_document"}, "admin": set()}
FIELDS = {
    "Case reference": "string",
    "Business links": "documentlink",
    "Accounting status": "string",
    "Capture ID": "string",
    "Capture part": "string",
    "Capture pair": "documentlink",
    "Retention basis": "string",
    "Retention event": "date",
    "Review date": "date",
    "Hold reference": "string",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def permissions(codenames):
    selected = Permission.objects.filter(
        content_type__app_label="documents", codename__in=codenames,
    )
    require(set(selected.values_list("codename", flat=True)) == codenames,
            "Unsupported native records permissions")
    return selected


def model_semantics(instance):
    return {
        field.name: field.get_prep_value(field.value_from_object(instance))
        for field in instance._meta.concrete_fields if not field.primary_key
    }


def private_semantics(actual, expected):
    require(model_semantics(actual) == model_semantics(expected),
            "Records workflow semantics differ")
    require(not any(getattr(actual, field.name).exists()
                    for field in actual._meta.many_to_many),
            "Records workflow has unexpected assignments or filters")


def names(manager):
    return set(manager.values_list("content_type__app_label", "codename"))


def expected_permissions(codenames):
    return {("documents", name) for name in codenames}


secret = json.loads(Path(os.environ["BARTL_RECORDS_SECRET"]).read_text())
action = os.environ["BARTL_RECORDS_ACTION"]
require(action in {"initialize", "check"}, "Unsupported records operation")
require(secret.get("format") == 1, "Unsupported records input format")
for role in ROLES:
    account = secret.get(role, {})
    require(account.get("username") == f"records-{role}", "Wrong records account identity")
    require(isinstance(account.get("password"), str) and 32 <= len(account["password"]) <= 1024,
            "Invalid records account credential")
    token = account.get("token")
    require(isinstance(token, str) and len(token) == 40 and all(c in "0123456789abcdef" for c in token),
            "Invalid records API credential")
require(len({secret[role]["token"] for role in ROLES}) == len(ROLES), "Distinct records credentials required")

with transaction.atomic():
    if action == "initialize":
        require(not User.objects.filter(username__in=["records-" + role for role in ROLES]).exists()
                and not Group.objects.filter(name=GROUP).exists()
                and not Workflow.objects.filter(name__in=[item[0] for item in WORKFLOWS]).exists()
                and not CustomField.objects.filter(name__in=FIELDS).exists(),
                "Records initialization refuses existing owned configuration")
        daily = Group.objects.create(name=GROUP)
        daily.permissions.set(permissions(DAILY))
        users = {}
        for role in ROLES:
            account = secret[role]
            user = User.objects.create_user(
                account["username"], password=account["password"],
                is_staff=role == "admin", is_superuser=role == "admin",
            )
            user.user_permissions.set(permissions(ROLES[role]))
            Token.objects.create(user=user, key=account["token"])
            users[role] = user
        # The reserved capture prefix selects a technical owner, never public access or a retention policy.
        for name, order, role, pattern in WORKFLOWS:
            trigger = WorkflowTrigger.objects.create(
                type=WorkflowTrigger.WorkflowTriggerType.CONSUMPTION, filter_filename=pattern,
            )
            assignment = WorkflowAction.objects.create(
                type=WorkflowAction.WorkflowActionType.ASSIGNMENT, assign_owner=users[role],
            )
            workflow = Workflow.objects.create(name=name, order=order, enabled=True)
            workflow.triggers.add(trigger)
            workflow.actions.add(assignment)
        for name, kind in FIELDS.items():
            CustomField.objects.create(name=name, data_type=kind)

    daily = Group.objects.get(name=GROUP)
    require(names(daily.permissions) == expected_permissions(DAILY), "Daily records rights differ")
    users = {}
    for role in ROLES:
        account = secret[role]
        user = User.objects.get(username=account["username"])
        require(user.is_active and user.is_superuser == (role == "admin")
                and user.is_staff == (role == "admin"), "Records account authority differs")
        require(user.check_password(account["password"]), "Records account credential differs")
        require(not user.groups.exists(), "Technical records account has unexpected groups")
        require(names(user.user_permissions) == expected_permissions(ROLES[role]),
                "Technical records rights differ")
        require(Token.objects.filter(user=user, key=account["token"]).exists(),
                "Records API credential differs")
        users[role] = user
    require(set(Workflow.objects.filter(enabled=True).values_list("name", flat=True))
            == {item[0] for item in WORKFLOWS}, "Unsupported enabled workflow")
    for name, order, role, pattern in WORKFLOWS:
        workflow = Workflow.objects.get(name=name)
        require(workflow.enabled and workflow.order == order, "Records ownership workflow is disabled or reordered")
        require(workflow.triggers.count() == 1 and workflow.actions.count() == 1,
                "Records ownership workflow differs")
        trigger = workflow.triggers.get()
        private_semantics(trigger, WorkflowTrigger(
            type=WorkflowTrigger.WorkflowTriggerType.CONSUMPTION, filter_filename=pattern,
        ))
        assignment = workflow.actions.get()
        private_semantics(assignment, WorkflowAction(
            type=WorkflowAction.WorkflowActionType.ASSIGNMENT, assign_owner=users[role],
        ))
    require(dict(CustomField.objects.filter(name__in=FIELDS).values_list("name", "data_type")) == FIELDS,
            "Records metadata profile differs")

print(json.dumps({"records_profile": 1, "status": "accepted", "daily_group": GROUP,
                  "intake": users["intake"].pk, "capture": users["capture"].pk,
                  "admin": users["admin"].pk}, sort_keys=True))
