"""Skills over MCP extension (`io.modelcontextprotocol/skills`, SEP-2640 Beta).

Serves static Agent Skills bundled under `app/mcp/skill_docs/` over MCP 2026-07-28:
- `skills/list` (paginated, cacheable)
- `skills/get` (single skill entry by `SKILL.md` URI, `-32602` on unknown URI)
- `resources/directory/read` (`directoryRead: true`, non-recursive direct children)
- `resources/read` via standard MCP `TextResource` entries under `skill://`

All digests (`sha256:<hex>`) and sizes are computed directly from the UTF-8 bytes
served by `resources/read`, and YAML frontmatter is parsed and validated against
the Agent Skills specification at load time.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import Path
import re
from typing import Any, Literal, TypeVar

from mcp.server.context import ServerRequestContext
from mcp.server.extension import Extension, MethodBinding, ResourceBinding
from mcp.server.mcpserver.resources import TextResource
from mcp.shared.exceptions import MCPError
from mcp_types import INVALID_PARAMS, PaginatedRequestParams, RequestParams, Resource
from mcp_types.version import MODERN_PROTOCOL_VERSIONS
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from app.core.settings import Settings

EXTENSION_ID = "io.modelcontextprotocol/skills"
SKILLS_ROOT = Path(__file__).resolve().parent / "skill_docs"
DEFAULT_TTL_MS = 300_000
DEFAULT_PAGE_SIZE = 50
MAX_RESOURCES_PER_SKILL = 512
MAX_TOTAL_BYTES_PER_SKILL = 16 * 1024 * 1024
EVENTS_SKILL_NAME = "istanbul-events-planner"

_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_FRONTMATTER_KEY_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_MODERN_VERSIONS = frozenset(MODERN_PROTOCOL_VERSIONS)


class SkillResourceEntry(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    uri: str
    digest: str
    size: int


class SkillEntry(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    uri: str
    frontmatter: dict[str, Any]
    resources: list[SkillResourceEntry]


class ListSkillsResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    result_type: Literal["complete"] = "complete"
    skills: list[SkillEntry]
    next_cursor: str | None = None
    ttl_ms: int
    cache_scope: Literal["public", "private"]


class GetSkillRequestParams(RequestParams):
    uri: str = Field(min_length=1)


class GetSkillResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    result_type: Literal["complete"] = "complete"
    skill: SkillEntry
    ttl_ms: int
    cache_scope: Literal["public", "private"]


class ReadResourceDirectoryRequestParams(PaginatedRequestParams):
    uri: str = Field(min_length=1)


class ReadResourceDirectoryResult(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    result_type: Literal["complete"] = "complete"
    resources: list[Resource]
    next_cursor: str | None = None
    ttl_ms: int
    cache_scope: Literal["public", "private"]


@dataclass(frozen=True)
class _LoadedSkillFile:
    uri: str
    rel_path: str
    name: str
    description: str | None
    mime_type: str
    text: str
    size: int
    digest: str


@dataclass(frozen=True)
class _LoadedSkill:
    name: str
    uri: str
    root_uri: str
    entry: SkillEntry
    files: tuple[_LoadedSkillFile, ...]


def parse_skill_frontmatter(text: str) -> dict[str, str]:
    """Parse flat YAML frontmatter from a SKILL.md document without external deps."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md must begin with YAML frontmatter delimited by '---'")
    end_idx = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise ValueError("SKILL.md frontmatter is missing a closing '---' delimiter")
    data: dict[str, str] = {}
    for raw_line in lines[1:end_idx]:
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(f"Unsupported frontmatter line: {raw_line!r}")
        key, raw_value = line.split(":", 1)
        key = key.strip()
        if not _FRONTMATTER_KEY_RE.match(key):
            raise ValueError(f"Invalid frontmatter key: {key!r}")
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        data[key] = value
    name = data.get("name", "")
    description = data.get("description", "")
    if not name or len(name) > 64 or not _SKILL_NAME_RE.match(name):
        raise ValueError(f"Invalid Agent Skill name: {name!r}")
    if not description or len(description) > 1024:
        raise ValueError(f"Invalid Agent Skill description for {name!r}")
    return data


def _mime_type_for(path: Path) -> str:
    if path.suffix.lower() in (".md", ".markdown"):
        return "text/markdown"
    guessed, _ = mimetypes.guess_type(path.name)
    return guessed or "text/plain"


def _load_skills(root: Path, *, enabled_filter: set[str] | None = None) -> tuple[_LoadedSkill, ...]:
    if not root.is_dir():
        return ()
    loaded: list[_LoadedSkill] = []
    for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            continue
        if enabled_filter is not None and skill_dir.name not in enabled_filter:
            continue
        md_text = skill_md.read_text(encoding="utf-8")
        frontmatter = parse_skill_frontmatter(md_text)
        if frontmatter["name"] != skill_dir.name:
            raise ValueError(
                f"Skill directory {skill_dir.name!r} must match frontmatter name {frontmatter['name']!r}"
            )
        skill_name = frontmatter["name"]
        root_uri = f"skill://{skill_name}"
        skill_uri = f"{root_uri}/SKILL.md"

        all_files = sorted(
            (p for p in skill_dir.rglob("*") if p.is_file()),
            key=lambda p: (0 if p == skill_md else 1, p.relative_to(skill_dir).as_posix()),
        )
        if len(all_files) > MAX_RESOURCES_PER_SKILL:
            raise ValueError(f"Skill {skill_name!r} exceeds {MAX_RESOURCES_PER_SKILL} file limit")

        loaded_files: list[_LoadedSkillFile] = []
        manifest: list[SkillResourceEntry] = []
        total_bytes = 0
        for file_path in all_files:
            rel_posix = file_path.relative_to(skill_dir).as_posix()
            uri = f"{root_uri}/{rel_posix}"
            text = file_path.read_text(encoding="utf-8")
            raw_bytes = text.encode("utf-8")
            size = len(raw_bytes)
            total_bytes += size
            digest = f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
            is_root_md = file_path == skill_md
            loaded_files.append(
                _LoadedSkillFile(
                    uri=uri,
                    rel_path=rel_posix,
                    name=skill_name if is_root_md else file_path.name,
                    description=frontmatter["description"] if is_root_md else f"Supporting file for {skill_name}: {rel_posix}",
                    mime_type=_mime_type_for(file_path),
                    text=text,
                    size=size,
                    digest=digest,
                )
            )
            manifest.append(SkillResourceEntry(uri=uri, digest=digest, size=size))

        if total_bytes > MAX_TOTAL_BYTES_PER_SKILL:
            raise ValueError(f"Skill {skill_name!r} exceeds {MAX_TOTAL_BYTES_PER_SKILL} byte limit")

        entry = SkillEntry(uri=skill_uri, frontmatter=dict(frontmatter), resources=manifest)
        loaded.append(
            _LoadedSkill(
                name=skill_name,
                uri=skill_uri,
                root_uri=root_uri,
                entry=entry,
                files=tuple(loaded_files),
            )
        )
    return tuple(loaded)


def _build_directories(skills: Sequence[_LoadedSkill]) -> dict[str, list[Resource]]:
    """Build non-recursive direct-child listings for every skill directory URI."""
    children: dict[str, dict[str, Resource]] = {}
    for skill in skills:
        children.setdefault(skill.root_uri, {})
        for item in skill.files:
            parts = item.rel_path.split("/")
            parent_uri = skill.root_uri
            for idx, segment in enumerate(parts[:-1]):
                dir_uri = f"{parent_uri}/{segment}"
                children.setdefault(parent_uri, {})[dir_uri] = Resource(
                    uri=dir_uri,
                    name=segment,
                    mime_type="inode/directory",
                )
                children.setdefault(dir_uri, {})
                parent_uri = dir_uri
            file_name = parts[-1]
            children.setdefault(parent_uri, {})[item.uri] = Resource(
                uri=item.uri,
                name=file_name,
                mime_type=item.mime_type,
                size=item.size,
            )
    return {
        dir_uri: [res for _, res in sorted(entries.items(), key=lambda kv: kv[0])]
        for dir_uri, entries in children.items()
    }


_T = TypeVar("_T")


def _paginate(
    items: Sequence[_T],
    cursor: str | None,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[_T], str | None]:
    offset = 0
    if cursor is not None:
        try:
            offset = int(cursor)
            if offset < 0:
                raise ValueError
        except ValueError:
            raise MCPError(code=INVALID_PARAMS, message=f"Invalid pagination cursor: {cursor!r}") from None
    page = list(items[offset : offset + page_size])
    next_offset = offset + page_size
    next_cursor = str(next_offset) if next_offset < len(items) else None
    return page, next_cursor


class IstanbulSkills(Extension):
    """SEP-2640 Skills over MCP extension for Istanbul MCP."""

    identifier = EXTENSION_ID

    def __init__(
        self,
        *,
        skills_root: Path = SKILLS_ROOT,
        events_enabled: bool = False,
        cache_scope: Literal["public", "private"] = "public",
        ttl_ms: int = DEFAULT_TTL_MS,
    ) -> None:
        all_dirs = sorted(p.name for p in skills_root.iterdir() if p.is_dir()) if skills_root.is_dir() else []
        enabled = {name for name in all_dirs if events_enabled or name != EVENTS_SKILL_NAME}
        self._skills = _load_skills(skills_root, enabled_filter=enabled)
        self._by_uri = {skill.uri: skill for skill in self._skills}
        self._directories = _build_directories(self._skills)
        self._cache_scope: Literal["public", "private"] = cache_scope
        self._ttl_ms = ttl_ms

    def settings(self) -> dict[str, Any]:
        return {"directoryRead": True}

    def resources(self) -> Sequence[ResourceBinding]:
        bindings: list[ResourceBinding] = []
        for skill in self._skills:
            for item in skill.files:
                bindings.append(
                    ResourceBinding(
                        resource=TextResource(
                            uri=item.uri,
                            name=item.name,
                            description=item.description,
                            mime_type=item.mime_type,
                            text=item.text,
                        )
                    )
                )
        return tuple(bindings)

    def methods(self) -> Sequence[MethodBinding]:
        return (
            MethodBinding(
                method="skills/list",
                params_type=PaginatedRequestParams,
                handler=self._handle_list_skills,
                protocol_versions=_MODERN_VERSIONS,
            ),
            MethodBinding(
                method="skills/get",
                params_type=GetSkillRequestParams,
                handler=self._handle_get_skill,
                protocol_versions=_MODERN_VERSIONS,
            ),
            MethodBinding(
                method="resources/directory/read",
                params_type=ReadResourceDirectoryRequestParams,
                handler=self._handle_read_directory,
                protocol_versions=_MODERN_VERSIONS,
            ),
        )

    async def _handle_list_skills(
        self,
        _ctx: ServerRequestContext[Any, Any],
        params: PaginatedRequestParams,
    ) -> ListSkillsResult:
        entries = [skill.entry for skill in self._skills]
        page, next_cursor = _paginate(entries, params.cursor)
        return ListSkillsResult(
            skills=page,
            next_cursor=next_cursor,
            ttl_ms=self._ttl_ms,
            cache_scope=self._cache_scope,
        )

    async def _handle_get_skill(
        self,
        _ctx: ServerRequestContext[Any, Any],
        params: GetSkillRequestParams,
    ) -> GetSkillResult:
        skill = self._by_uri.get(params.uri)
        if skill is None:
            raise MCPError(code=INVALID_PARAMS, message=f"No skill is served at {params.uri}")
        return GetSkillResult(
            skill=skill.entry,
            ttl_ms=self._ttl_ms,
            cache_scope=self._cache_scope,
        )

    async def _handle_read_directory(
        self,
        _ctx: ServerRequestContext[Any, Any],
        params: ReadResourceDirectoryRequestParams,
    ) -> ReadResourceDirectoryResult:
        children = self._directories.get(params.uri)
        if children is None:
            raise MCPError(code=INVALID_PARAMS, message=f"{params.uri} is not a directory resource")
        page, next_cursor = _paginate(children, params.cursor)
        return ReadResourceDirectoryResult(
            resources=page,
            next_cursor=next_cursor,
            ttl_ms=self._ttl_ms,
            cache_scope=self._cache_scope,
        )


def create_istanbul_skills(settings: Settings) -> IstanbulSkills:
    scope: Literal["public", "private"] = (
        "private" if (settings.mcp_auth_required or settings.mcp_api_keys) else "public"
    )
    return IstanbulSkills(
        events_enabled=settings.events_enabled,
        cache_scope=scope,
    )
