"""Example: generating UUIDv7 task IDs and cross-ledger references."""

from ledgercore import LedgerUuidResourceRef, Uuid7IdFormat

task_ids = Uuid7IdFormat(prefix="task")
task_id = task_ids.new()
task_uuid = task_ids.parse(task_id)

ref = LedgerUuidResourceRef(
    ledger="tl",
    kind="task",
    resource_uuid=task_uuid,
)

assert task_id.startswith("task-")
assert ref.global_ref == f"tl:{task_id}"
assert ref.file_ref == f"tl-{task_id}"

print(task_id)
print(ref.global_ref)
