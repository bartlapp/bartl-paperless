# Explicit native-model administration under the lifecycle owner's DB/media lock.
# No retention calculation, automatic approval, global audit pruning or foreign-copy deletion.
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from auditlog.models import LogEntry
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import transaction
from django.db.models import Q
from documents.models import CustomFieldInstance, Document, Note, PaperlessTask
from documents.permissions import set_permissions_for_object
from documents.tasks import empty_trash
from guardian.shortcuts import get_groups_with_perms, get_users_with_perms


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def digest(value):
    return hashlib.sha256(value).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def file_digest(path):
    value = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def media_path(value):
    path = Path(value)
    root = Path(settings.MEDIA_ROOT)
    require(path.is_absolute() and path.is_relative_to(root) and path != root,
            "Residue path is outside native media")
    require(not any(part.is_symlink() for part in [path, *path.parents]), "Symlink media is not supported")
    return path


def durable_json(path, value):
    temporary = path.with_suffix(".pending")
    with temporary.open("w") as target:
        json.dump(value, target, sort_keys=True)
        target.flush()
        os.fsync(target.fileno())
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def task_identity(task):
    return digest(canonical({"task_id": task.task_id, "status": task.status,
                             "owner": task.owner_id, "input": task.input_data,
                             "result": task.result_data}))


source = Path(os.environ["BARTL_RECORDS_DECISIONS"])
raw = source.read_bytes()
decisions = json.loads(raw)
installation = os.environ["BARTL_RECORDS_INSTALLATION"]
require(len(installation) == 32 and all(c in "0123456789abcdef" for c in installation),
        "Bound installation identity required")
require(decisions.get("format") == 1 and type(decisions.get("revision")) is int
        and decisions["revision"] > 0, "Invalid current decision format")
require(set(decisions) <= {"format", "revision", "issuer", "paperless", "installation",
                          "approvedBy", "approvedAt", "delete", "restrict", "hold"},
        "Unsupported records decision field")
require(isinstance(decisions.get("approvedBy"), str) and decisions["approvedBy"].strip(),
        "Explicit records approver required")
require(datetime.fromisoformat(decisions["approvedAt"].replace("Z", "+00:00")).tzinfo is not None,
        "Unambiguous records approval time required")
providers = json.loads(os.environ["PAPERLESS_SOCIALACCOUNT_PROVIDERS"])["openid_connect"]["APPS"]
require(len(providers) == 1 and decisions["issuer"] == providers[0]["settings"]["server_url"]
        and decisions["paperless"] == os.environ["PAPERLESS_URL"], "Foreign records decision identity")
selected = {}
for action in ("delete", "restrict", "hold"):
    require(isinstance(decisions.get(action), list), "Complete records decision inventory required")
    for entry in decisions[action]:
        require(set(entry) <= {"id", "sha256", "reason", "versions"}, "Unsupported selected-record field")
        require(type(entry.get("id")) is int and entry["id"] > 0
                and isinstance(entry.get("sha256"), str) and len(entry["sha256"]) == 64
                and all(c in "0123456789abcdef" for c in entry["sha256"]), "Exact original identity required")
        require(isinstance(entry.get("reason"), str) and entry["reason"].strip(), "Record decision reason required")
        item = selected.setdefault(entry["id"], {"sha256": entry["sha256"], "actions": set(),
                                                "versions": entry.get("versions")})
        require(item["sha256"] == entry["sha256"] and action not in item["actions"], "Contradictory record identity")
        require(not ("delete" in item["actions"] or (action == "delete" and item["actions"])),
                "Disposal conflicts with hold or restriction")
        item["actions"].add(action)
if selected:
    require(decisions.get("installation") == installation, "Current decisions must bind the accepted installation")

secret = json.loads(Path(os.environ["BARTL_RECORDS_SECRET"]).read_text())
admin = User.objects.get(username=secret["admin"]["username"])
require(admin.is_active and admin.is_superuser, "Protected records administrator missing")
require(not PaperlessTask.objects.filter(status__in=[PaperlessTask.Status.PENDING, PaperlessTask.Status.STARTED]).exists(),
        "Records administration requires settled native work")
state_root = Path(os.environ["BARTL_RECORDS_STATE"])
require(not any(part.is_symlink() for part in [state_root, *state_root.parents]), "Invalid records operation storage")
state_root.mkdir(mode=0o700, parents=True, exist_ok=True)
require(state_root.is_dir() and not state_root.stat().st_mode & 0o077, "Protected records operation storage required")
decisions_digest = digest(raw)
journal = state_root / (decisions_digest + ".json")
require(not journal.is_symlink(), "Invalid records operation journal")
models = {"documents": Document, "notes": Note, "fields": CustomFieldInstance}

if journal.exists():
    plan = json.loads(journal.read_text())
    require(plan.get("format") == 1 and plan.get("installation") == installation
            and plan.get("decisionsDigest") == decisions_digest, "Foreign records operation journal")
else:
    plan = {"format": 1, "installation": installation, "decisionsDigest": decisions_digest,
            "phase": "prepared", "roots": {}, "objects": {name: [] for name in models},
            "files": [], "tasks": []}
    # All identities and every selected version are checked before the first mutation.
    for identifier, item in selected.items():
        document = Document.global_objects.filter(pk=identifier).first()
        require(document is not None, "Missing selected record without its prior verified residue plan")
        require(document.root_document_id is None, "Select the record root, not an individual version")
        require(document.deleted_at is None, "Selected record is already in trash without an operation plan")
        original = media_path(document.source_path)
        require(original.is_file() and file_digest(original) == item["sha256"], "Selected original missing or changed")
        family = list(Document.global_objects.filter(Q(pk=identifier) | Q(root_document_id=identifier)).order_by("pk"))
        versions = []
        family_files = []
        for version in family:
            paths = [version.source_path, version.thumbnail_path]
            if version.has_archive_version:
                paths.append(version.archive_path)
            original_hash = None
            for value in paths:
                path = media_path(value)
                require(path.is_file(), "Expected native document file is missing")
                checksum = file_digest(path)
                family_files.append({"path": str(path), "sha256": checksum})
                if path == Path(version.source_path):
                    original_hash = checksum
            versions.append({"id": version.pk, "sha256": original_hash})
        if "delete" in item["actions"] and len(versions) > 1:
            require(item["versions"] == versions, "Disposal requires explicit identities for every version")
        plan["roots"][str(identifier)] = {"sha256": item["sha256"], "members": versions}
        if "delete" in item["actions"]:
            plan["objects"]["documents"].extend(version["id"] for version in versions)
            plan["files"].extend(family_files)
    ids = plan["objects"]["documents"]
    plan["objects"]["notes"] = list(Note.global_objects.filter(document_id__in=ids).values_list("pk", flat=True))
    plan["objects"]["fields"] = list(CustomFieldInstance.global_objects.filter(document_id__in=ids).values_list("pk", flat=True))
    for task in PaperlessTask.objects.all().iterator():
        related = set(task.related_document_ids)
        if related & set(ids):
            require(related <= set(ids), "Related task also belongs to a retained record")
            require(task.status in [PaperlessTask.Status.SUCCESS, PaperlessTask.Status.FAILURE, PaperlessTask.Status.REVOKED],
                    "Selected task is not settled")
            plan["tasks"].append({"id": task.pk, "task_id": task.task_id, "identity": task_identity(task)})
    # Unknown earlier hard deletions cannot be attributed from vanished child rows.
    # Refuse rather than pruning unrelated orphan audit history.
    if ids:
        for model in (Note, CustomFieldInstance):
            content_type = ContentType.objects.get_for_model(model)
            for entry in LogEntry.objects.filter(content_type=content_type).only("object_id").iterator():
                require(not entry.object_id or model.global_objects.filter(pk=entry.object_id).exists(),
                        "Unattributed prior orphan audit history requires an explicit operator decision")
    durable_json(journal, plan)

require(set(plan["roots"]) == {str(identifier) for identifier in selected}, "Incomplete retained operation plan")
# A retry may resume only its own durable, exact pre-delete inventory.
for identifier, item in selected.items():
    root = plan["roots"][str(identifier)]
    require(root["sha256"] == item["sha256"], "Retained original identity differs")
    planned_ids = {version["id"] for version in root["members"]}
    current = list(Document.global_objects.filter(Q(pk=identifier) | Q(root_document_id=identifier)))
    require({document.pk for document in current} <= planned_ids, "Record acquired an unapproved version")
    for document in current:
        expected = next(version["sha256"] for version in root["members"] if version["id"] == document.pk)
        path = media_path(document.source_path)
        require(path.is_file() and file_digest(path) == expected, "Selected version identity changed")
    if "delete" not in item["actions"]:
        require({document.pk for document in current} == planned_ids, "Retained or held record is incomplete")

for identifier, item in selected.items():
    if "restrict" in item["actions"]:
        with transaction.atomic():
            for document in Document.global_objects.filter(pk__in=[v["id"] for v in plan["roots"][str(identifier)]["members"]]):
                set_permissions_for_object({"view": {"users": [], "groups": []},
                                            "change": {"users": [], "groups": []}}, document)
                document.owner = admin
                document.save(update_fields=["owner"])
    if "delete" in item["actions"]:
        document = Document.objects.filter(pk=identifier).first()
        if document is not None:
            document.delete()
trash_ids = list(Document.deleted_objects.filter(pk__in=plan["objects"]["documents"]).values_list("pk", flat=True))
if trash_ids:
    empty_trash(doc_ids=trash_ids)
for name, model in models.items():
    identifiers = plan["objects"][name]
    require(not model.global_objects.filter(pk__in=identifiers).exists(), "Native purge is incomplete")
    # Match native prune's existence guard, but only for this approved plan's object IDs.
    LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(model),
                            object_id__in=[str(identifier) for identifier in identifiers]).delete()
for item in plan["files"]:
    path = media_path(item["path"])
    if path.exists():
        require(path.is_file() and file_digest(path) == item["sha256"], "Orphan file no longer matches approved inventory")
        path.unlink()
for item in plan["tasks"]:
    task = PaperlessTask.objects.filter(pk=item["id"]).first()
    if task is not None:
        require(task.task_id == item["task_id"] and task_identity(task) == item["identity"], "Selected task history changed")
        task.delete()
for name, model in models.items():
    ids = plan["objects"][name]
    require(not model.global_objects.filter(pk__in=ids).exists()
            and not LogEntry.objects.filter(content_type=ContentType.objects.get_for_model(model),
                                             object_id__in=[str(identifier) for identifier in ids]).exists(),
            "Selected native objects or audit residues remain")
require(not any(media_path(item["path"]).exists() for item in plan["files"]), "Selected media residues remain")
require(not PaperlessTask.objects.filter(pk__in=[item["id"] for item in plan["tasks"]]).exists(),
        "Selected native task history remains")
for identifier, item in selected.items():
    if "delete" in item["actions"]:
        continue
    for version in plan["roots"][str(identifier)]["members"]:
        document = Document.objects.get(pk=version["id"])
        require(file_digest(media_path(document.source_path)) == version["sha256"], "Retained original changed")
        if "restrict" in item["actions"]:
            require(document.owner_id == admin.pk
                    and not get_users_with_perms(document, with_superusers=False, with_group_users=False).exists()
                    and not get_groups_with_perms(document).exists(), "Restriction did not remove ordinary access")
plan["phase"] = "verified"
durable_json(journal, plan)
print(json.dumps({"state": "records-reconciled", "installation": installation,
                  "decisionsDigest": decisions_digest, "revision": decisions["revision"],
                  "deleted": [entry["id"] for entry in decisions["delete"]],
                  "restricted": [entry["id"] for entry in decisions["restrict"]],
                  "held": [entry["id"] for entry in decisions["hold"]],
                  "residueVerified": True}, sort_keys=True))
