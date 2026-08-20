"""Issue read-only MCP tools."""

import mimetypes
from pathlib import Path
from typing import Annotated, Any

from mcp.server import FastMCP
from mcp.server.fastmcp import Context
from mcp.types import ToolAnnotations
from pydantic import Field

from mcp_tracker.mcp.context import AppContext
from mcp_tracker.mcp.errors import TrackerError
from mcp_tracker.mcp.params import (
    CursorPerPageParam,
    IssueID,
    IssueIDs,
    PageParam,
    PerPageParam,
    YTQuery,
)
from mcp_tracker.mcp.tools._access import check_issue_access, check_queue_access
from mcp_tracker.mcp.utils import (
    get_yandex_auth,
    save_issue_attachment_file,
    set_non_needed_fields_null,
)
from mcp_tracker.settings import Settings
from mcp_tracker.tracker.proto.types.issues import (
    ChangelogPage,
    ChecklistItem,
    DownloadedIssueAttachment,
    Issue,
    IssueAttachment,
    IssueComment,
    IssueFieldsEnum,
    IssueLink,
    IssueLocalFieldMatch,
    IssuesByLocalFieldResult,
    IssueTransition,
    Worklog,
)


def register_issue_read_tools(settings: Settings, mcp: FastMCP[Any]) -> None:
    """Register issue read-only tools."""

    @mcp.tool(
        title="Get Issue",
        description="Get a Yandex Tracker issue by its id",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issue_get(
        ctx: Context[Any, AppContext],
        issue_id: IssueID,
        include_description: Annotated[
            bool,
            Field(
                description="Whether to include issue description in the issues result. "
                "It can be large, so use only when needed.",
            ),
        ] = True,
    ) -> Issue:
        check_issue_access(settings, issue_id)

        issue = await ctx.request_context.lifespan_context.issues.issue_get(
            issue_id,
            auth=get_yandex_auth(ctx),
        )

        if not include_description:
            issue.description = None

        return issue

    @mcp.tool(
        title="Get Issue Comments",
        description="Get comments of a Yandex Tracker issue by its id",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issue_get_comments(
        ctx: Context[Any, AppContext],
        issue_id: IssueID,
    ) -> list[IssueComment]:
        check_issue_access(settings, issue_id)

        return await ctx.request_context.lifespan_context.issues.issue_get_comments(
            issue_id,
            auth=get_yandex_auth(ctx),
        )

    @mcp.tool(
        title="Get Issue Links",
        description="Get a Yandex Tracker issue related links to other issues by its id",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issue_get_links(
        ctx: Context[Any, AppContext],
        issue_id: IssueID,
    ) -> list[IssueLink]:
        check_issue_access(settings, issue_id)

        return await ctx.request_context.lifespan_context.issues.issues_get_links(
            issue_id,
            auth=get_yandex_auth(ctx),
        )

    @mcp.tool(
        title="Find Issues",
        description="Find Yandex Tracker issues by queue and/or created date",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issues_find(
        ctx: Context[Any, AppContext],
        query: YTQuery,
        include_description: Annotated[
            bool,
            Field(
                description="Whether to include issue description in the issues result. It can be large, so use only when needed.",
            ),
        ] = False,
        fields: Annotated[
            list[IssueFieldsEnum] | None,
            Field(
                description="Fields to include in the response. In order to not pollute context window - select "
                "appropriate fields beforehand. Not specifying fields will return all available."
            ),
        ] = None,
        page: PageParam = 1,
        per_page: PerPageParam = 100,
    ) -> list[Issue]:
        issues = await ctx.request_context.lifespan_context.issues.issues_find(
            query=query,
            per_page=per_page,
            page=page,
            auth=get_yandex_auth(ctx),
        )

        if not include_description:
            for issue in issues:
                issue.description = None  # Clear description to save context

        if fields is not None:
            set_non_needed_fields_null(issues, {f.name for f in fields})

        return issues

    @mcp.tool(
        title="Count Issues",
        description="Get the count of Yandex Tracker issues matching a query",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issues_count(
        ctx: Context[Any, AppContext],
        query: YTQuery,
    ) -> int:
        return await ctx.request_context.lifespan_context.issues.issues_count(
            query,
            auth=get_yandex_auth(ctx),
        )

    @mcp.tool(
        title="Find Issues By Local Field",
        description=(
            "Find issues in a queue by the value of a queue-local field (e.g. 'organization' / "
            "'client' in a support queue). Use this instead of `issues_find`/`issues_count` when "
            'Tracker rejects `<QUEUE>.<field_key>: "value"` in the query with a 422 error '
            "'Фильтр <field> не существует' — that means the field isn't registered as a search "
            "filter on Tracker's side, which is common for plain text local fields. This tool "
            "works around it by paging through the queue's issues and matching the field value "
            "client-side, so it is slower than a real filter and bounded by max_pages."
        ),
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issues_find_by_local_field(
        ctx: Context[Any, AppContext],
        queue: Annotated[str, Field(description="Queue key to search in, e.g. 'SUP'")],
        field_key: Annotated[
            str,
            Field(
                description="Local field key to match, e.g. 'organization' "
                "(see queue_get_fields for available keys)"
            ),
        ],
        values: Annotated[
            list[str],
            Field(
                description="Field values to match, case-insensitive exact match. "
                "An issue is a hit if its field value equals any of these."
            ),
        ],
        extra_query: Annotated[
            str | None,
            Field(
                description="Additional YQL clause AND-ed with the queue filter, "
                "e.g. 'Resolution: unresolved()'"
            ),
        ] = None,
        max_pages: Annotated[
            int,
            Field(
                description="Safety cap on the number of 100-issue pages scanned",
                ge=1,
                le=200,
            ),
        ] = 50,
    ) -> IssuesByLocalFieldResult:
        check_queue_access(settings, queue)

        auth = get_yandex_auth(ctx)
        lifespan = ctx.request_context.lifespan_context

        local_fields = await lifespan.queues.queues_get_local_fields(queue, auth=auth)
        field = next((f for f in local_fields if f.key == field_key), None)
        if field is None or field.id is None:
            known = sorted(f.key for f in local_fields if f.key)
            raise TrackerError(
                f"Local field `{field_key}` not found in queue `{queue}`. "
                f"Available local fields: {', '.join(known)}"
            )

        query = f'Queue: "{queue}"'
        if extra_query:
            query = f"{query} AND {extra_query}"

        wanted = {v.strip().lower() for v in values}
        matches: list[IssueLocalFieldMatch] = []
        pages_scanned = 0
        truncated = False

        for page in range(1, max_pages + 1):
            issues = await lifespan.issues.issues_find(
                query=query, per_page=100, page=page, auth=auth
            )
            pages_scanned = page
            if not issues:
                break

            for issue in issues:
                raw_value = (issue.model_extra or {}).get(field.id)
                if isinstance(raw_value, str) and raw_value.strip().lower() in wanted:
                    matches.append(
                        IssueLocalFieldMatch(
                            key=issue.key or "",
                            summary=issue.summary,
                            status=issue.status.display if issue.status else None,
                            assignee=issue.assignee.display if issue.assignee else None,
                            created_at=issue.created_at,
                            field_value=raw_value,
                        )
                    )

            if len(issues) < 100:
                break
        else:
            truncated = True

        return IssuesByLocalFieldResult(
            matches=matches,
            pages_scanned=pages_scanned,
            truncated=truncated,
        )

    @mcp.tool(
        title="Get Issue Worklogs",
        description="Get worklogs of a Yandex Tracker issue by its id",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issue_get_worklogs(
        ctx: Context[Any, AppContext],
        issue_ids: IssueIDs,
    ) -> dict[str, list[Worklog]]:
        for issue_id in issue_ids:
            check_issue_access(settings, issue_id)

        result: dict[str, list[Worklog]] = {}
        for issue_id in issue_ids:
            worklogs = (
                await ctx.request_context.lifespan_context.issues.issue_get_worklogs(
                    issue_id,
                    auth=get_yandex_auth(ctx),
                )
            )
            result[issue_id] = worklogs or []

        return result

    @mcp.tool(
        title="Get Issue Attachments",
        description="Get attachments of a Yandex Tracker issue by its id",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issue_get_attachments(
        ctx: Context[Any, AppContext],
        issue_id: IssueID,
    ) -> list[IssueAttachment]:
        check_issue_access(settings, issue_id)

        return await ctx.request_context.lifespan_context.issues.issue_get_attachments(
            issue_id,
            auth=get_yandex_auth(ctx),
        )

    @mcp.tool(
        title="Download Issue Attachment",
        description=(
            "Download a Yandex Tracker issue attachment and save it to a local directory. "
            "Returns the absolute path to the saved file and its metadata."
        ),
    )
    async def issue_download_attachment(
        ctx: Context[Any, AppContext],
        issue_id: IssueID,
        attachment_id: str,
        file_name: str,
        save_directory: Annotated[
            str,
            Field(
                description=(
                    "Directory to save the downloaded file. "
                    "MUST be an absolute path, for example "
                    "/Users/me/projects/myproject/tmp/tracker-attachments/. "
                    "Relative paths resolve against the MCP server process cwd, "
                    "not your project, so pass an absolute path."
                ),
            ),
        ],
    ) -> DownloadedIssueAttachment:
        check_issue_access(settings, issue_id)

        data = (
            await ctx.request_context.lifespan_context.issues.issue_download_attachment(
                issue_id,
                attachment_id,
                file_name,
                auth=get_yandex_auth(ctx),
            )
        )

        local_path = save_issue_attachment_file(
            data,
            issue_id=issue_id,
            attachment_id=attachment_id,
            file_name=file_name,
            save_directory=save_directory,
        )
        safe_name = Path(file_name).name
        mime_type, _ = mimetypes.guess_type(safe_name)

        return DownloadedIssueAttachment(
            local_path=str(local_path),
            name=safe_name,
            mime_type=mime_type or "application/octet-stream",
            size=len(data),
        )

    @mcp.tool(
        title="Get Issue Checklist",
        description="Get checklist items of a Yandex Tracker issue by its id",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issue_get_checklist(
        ctx: Context[Any, AppContext],
        issue_id: IssueID,
    ) -> list[ChecklistItem]:
        check_issue_access(settings, issue_id)

        return await ctx.request_context.lifespan_context.issues.issue_get_checklist(
            issue_id,
            auth=get_yandex_auth(ctx),
        )

    @mcp.tool(
        title="Get Issue Transitions",
        description="Get possible status transitions for a Yandex Tracker issue. "
        "Returns list of available transitions that can be performed on the issue.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issue_get_transitions(
        ctx: Context[Any, AppContext],
        issue_id: IssueID,
    ) -> list[IssueTransition]:
        check_issue_access(settings, issue_id)

        return await ctx.request_context.lifespan_context.issues.issue_get_transitions(
            issue_id,
            auth=get_yandex_auth(ctx),
        )

    @mcp.tool(
        title="Get Issue Changelog",
        description="Get the change history (changelog) of a Yandex Tracker issue by its id: "
        "status transitions, field edits (who changed what from -> to and when), "
        "comment changes and executed triggers. "
        "Returns a page of entries plus 'next_cursor'. To fetch the next page, pass "
        "'next_cursor' from the previous result as the 'cursor' argument; when "
        "'next_cursor' is null there are no more pages.",
        annotations=ToolAnnotations(readOnlyHint=True),
    )
    async def issue_get_changelog(
        ctx: Context[Any, AppContext],
        issue_id: IssueID,
        per_page: CursorPerPageParam = 50,
        cursor: Annotated[
            str | None,
            Field(
                description="Cursor for the next page: the 'next_cursor' value returned by "
                "the previous call. Leave empty for the first page.",
            ),
        ] = None,
        field: Annotated[
            str | None,
            Field(
                description="Optional field key to filter the changelog by "
                "(e.g. 'status' to only see status changes).",
            ),
        ] = None,
        type: Annotated[
            str | None,
            Field(
                description="Optional change type to filter by (e.g. 'IssueWorkflow' for status transitions).",
            ),
        ] = None,
    ) -> ChangelogPage:
        check_issue_access(settings, issue_id)

        return await ctx.request_context.lifespan_context.issues.issue_get_changelog(
            issue_id,
            per_page=per_page,
            cursor=cursor,
            field=field,
            type=type,
            auth=get_yandex_auth(ctx),
        )
