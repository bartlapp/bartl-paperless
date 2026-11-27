"""Run with native manage.py shell on a disposable synthetic library.

WORKFLOW_CHECK=prepare follows ingestion of 'Synthetic workflow history'.
WORKFLOW_CHECK=verify follows package capture/reconstruction, without creating
or repairing workflow execution records. The same assertion exposes format-1
export loss and verifies complete-state reconstruction.
"""
import json
import os

from documents.models import Document, Tag, Workflow, WorkflowTrigger, WorkflowAction, WorkflowRun
from documents.tasks import check_scheduled_workflows

mode = os.environ['WORKFLOW_CHECK']
document = Document.objects.get(title='Synthetic workflow history')
if mode == 'prepare':
    assert not Workflow.objects.filter(name='Synthetic nonrecurring schedule').exists()
    tag = Tag.objects.create(name='Synthetic scheduled assignment', matching_algorithm=0)
    trigger = WorkflowTrigger.objects.create(
        type=WorkflowTrigger.WorkflowTriggerType.SCHEDULED,
        schedule_date_field='added', schedule_offset_days=0, schedule_is_recurring=False)
    action = WorkflowAction.objects.create(type=WorkflowAction.WorkflowActionType.ASSIGNMENT)
    action.assign_tags.add(tag)
    workflow = Workflow.objects.create(name='Synthetic nonrecurring schedule')
    workflow.triggers.add(trigger)
    workflow.actions.add(action)
    check_scheduled_workflows()
    assert document.tags.filter(pk=tag.pk).exists(), 'Native workflow did not assign metadata'
    assert WorkflowRun.objects.filter(document=document, workflow=workflow).count() == 1
    document.tags.remove(tag)
    check_scheduled_workflows()
    assert not document.tags.filter(pk=tag.pk).exists(), 'Scheduler repeated completed workflow before capture'
    print(json.dumps({'phase': 'baseline', 'document': document.pk, 'workflow': workflow.pk,
                      'runs': list(WorkflowRun.objects.filter(document=document, workflow=workflow)
                                   .values('id', 'run_at'))}, default=str))
elif mode == 'verify':
    workflow = Workflow.objects.get(name='Synthetic nonrecurring schedule')
    tag = Tag.objects.get(name='Synthetic scheduled assignment')
    before = WorkflowRun.objects.filter(document=document, workflow=workflow).count()
    assert not document.tags.filter(pk=tag.pk).exists(), 'Later corrected metadata missing before scheduler'
    check_scheduled_workflows()
    assigned = document.tags.filter(pk=tag.pk).exists()
    after = WorkflowRun.objects.filter(document=document, workflow=workflow).count()
    print(json.dumps({'phase': 'after-reconstruction-scheduler', 'runsBefore': before,
                      'runsAfter': after, 'incorrectlyReassigned': assigned}))
    assert before == 1 and after == 1 and not assigned, (
        'Reconstruction lost workflow execution history and scheduler reverted later metadata correction')
else:
    raise ValueError(mode)
