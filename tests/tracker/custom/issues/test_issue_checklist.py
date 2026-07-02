import datetime

import pytest
from aioresponses import aioresponses

from mcp_tracker.tracker.custom.client import TrackerClient
from mcp_tracker.tracker.custom.errors import IssueNotFound
from mcp_tracker.tracker.proto.types.inputs import ChecklistItemDeadlineInput
from mcp_tracker.tracker.proto.types.issues import ChecklistItem

# Write endpoints return the full issue object with the updated `checklistItems`.
_ISSUE_WITH_CHECKLIST = {
    "self": "https://api.tracker.yandex.net/v3/issues/TEST-123",
    "id": "issue-1",
    "key": "TEST-123",
    "checklistItems": [
        {
            "self": "https://api.tracker.yandex.net/v3/issues/TEST-123/checklistItems/1",
            "id": "item-1",
            "text": "Buy milk",
            "checked": False,
            "checklistItemType": "standard",
        }
    ],
}


class TestIssueGetChecklist:
    async def test_success(self, tracker_client: TrackerClient) -> None:
        checklist_data = {
            "self": "https://api.tracker.yandex.net/v3/issues/TEST-123/checklistItems/1",
            "id": "checklist-123",
            "text": "Complete task A",
            "checked": False,
            "checklistItemType": "standard",
        }
        checklist_response = [checklist_data]

        with aioresponses() as m:
            m.get(
                "https://api.tracker.yandex.net/v3/issues/TEST-123/checklistItems",
                payload=checklist_response,
            )

            result = await tracker_client.issue_get_checklist("TEST-123")

            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], ChecklistItem)
            assert result[0].text == "Complete task A"

    async def test_not_found(self, tracker_client: TrackerClient) -> None:
        with aioresponses() as m:
            m.get(
                "https://api.tracker.yandex.net/v3/issues/NOTFOUND-123/checklistItems",
                status=404,
            )

            with pytest.raises(IssueNotFound) as exc_info:
                await tracker_client.issue_get_checklist("NOTFOUND-123")

            assert exc_info.value.issue_id == "NOTFOUND-123"


class TestIssueAddChecklistItem:
    async def test_success(self, tracker_client: TrackerClient) -> None:
        with aioresponses() as m:
            m.post(
                "https://api.tracker.yandex.net/v3/issues/TEST-123/checklistItems",
                payload=_ISSUE_WITH_CHECKLIST,
            )

            result = await tracker_client.issue_add_checklist_item(
                "TEST-123", text="Buy milk"
            )

            assert isinstance(result, list)
            assert len(result) == 1
            assert isinstance(result[0], ChecklistItem)
            assert result[0].text == "Buy milk"

    async def test_sends_optional_fields(self, tracker_client: TrackerClient) -> None:
        deadline = ChecklistItemDeadlineInput(
            date=datetime.datetime(2026, 7, 10, tzinfo=datetime.timezone.utc),
            deadline_type="date",
        )

        with aioresponses() as m:
            m.post(
                "https://api.tracker.yandex.net/v3/issues/TEST-123/checklistItems",
                payload=_ISSUE_WITH_CHECKLIST,
            )

            await tracker_client.issue_add_checklist_item(
                "TEST-123",
                text="Buy milk",
                checked=True,
                assignee="ivan",
                deadline=deadline,
            )

            request = next(iter(m.requests.values()))[0]
            body = request.kwargs["json"]
            assert body["text"] == "Buy milk"
            assert body["checked"] is True
            assert body["assignee"] == "ivan"
            assert body["deadline"]["deadlineType"] == "date"
            assert body["deadline"]["date"] == deadline.date.isoformat()

    async def test_not_found(self, tracker_client: TrackerClient) -> None:
        with aioresponses() as m:
            m.post(
                "https://api.tracker.yandex.net/v3/issues/NOTFOUND-123/checklistItems",
                status=404,
            )

            with pytest.raises(IssueNotFound) as exc_info:
                await tracker_client.issue_add_checklist_item("NOTFOUND-123", text="x")

            assert exc_info.value.issue_id == "NOTFOUND-123"


class TestIssueUpdateChecklistItem:
    async def test_success(self, tracker_client: TrackerClient) -> None:
        with aioresponses() as m:
            m.patch(
                "https://api.tracker.yandex.net/v3/issues/TEST-123/checklistItems/item-1",
                payload=_ISSUE_WITH_CHECKLIST,
            )

            result = await tracker_client.issue_update_checklist_item(
                "TEST-123", "item-1", checked=True
            )

            assert isinstance(result, list)
            assert result[0].text == "Buy milk"

    async def test_sends_only_provided_fields(
        self, tracker_client: TrackerClient
    ) -> None:
        with aioresponses() as m:
            m.patch(
                "https://api.tracker.yandex.net/v3/issues/TEST-123/checklistItems/item-1",
                payload=_ISSUE_WITH_CHECKLIST,
            )

            await tracker_client.issue_update_checklist_item(
                "TEST-123", "item-1", text="New text"
            )

            request = next(iter(m.requests.values()))[0]
            body = request.kwargs["json"]
            assert body == {"text": "New text"}

    async def test_not_found(self, tracker_client: TrackerClient) -> None:
        with aioresponses() as m:
            m.patch(
                "https://api.tracker.yandex.net/v3/issues/NOTFOUND-123/checklistItems/item-1",
                status=404,
            )

            with pytest.raises(IssueNotFound) as exc_info:
                await tracker_client.issue_update_checklist_item(
                    "NOTFOUND-123", "item-1", text="x"
                )

            assert exc_info.value.issue_id == "NOTFOUND-123"


class TestIssueDeleteChecklistItem:
    async def test_success(self, tracker_client: TrackerClient) -> None:
        with aioresponses() as m:
            m.delete(
                "https://api.tracker.yandex.net/v3/issues/TEST-123/checklistItems/item-1",
                payload={**_ISSUE_WITH_CHECKLIST, "checklistItems": []},
            )

            result = await tracker_client.issue_delete_checklist_item(
                "TEST-123", "item-1"
            )

            assert result == []

    async def test_not_found(self, tracker_client: TrackerClient) -> None:
        with aioresponses() as m:
            m.delete(
                "https://api.tracker.yandex.net/v3/issues/NOTFOUND-123/checklistItems/item-1",
                status=404,
            )

            with pytest.raises(IssueNotFound) as exc_info:
                await tracker_client.issue_delete_checklist_item(
                    "NOTFOUND-123", "item-1"
                )

            assert exc_info.value.issue_id == "NOTFOUND-123"


class TestIssueDeleteAllChecklistItems:
    async def test_success(self, tracker_client: TrackerClient) -> None:
        with aioresponses() as m:
            m.delete(
                "https://api.tracker.yandex.net/v3/issues/TEST-123/checklists",
                payload={**_ISSUE_WITH_CHECKLIST, "checklistItems": []},
            )

            result = await tracker_client.issue_delete_all_checklist_items("TEST-123")

            assert result == []

    async def test_not_found(self, tracker_client: TrackerClient) -> None:
        with aioresponses() as m:
            m.delete(
                "https://api.tracker.yandex.net/v3/issues/NOTFOUND-123/checklists",
                status=404,
            )

            with pytest.raises(IssueNotFound) as exc_info:
                await tracker_client.issue_delete_all_checklist_items("NOTFOUND-123")

            assert exc_info.value.issue_id == "NOTFOUND-123"
