from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from ..core.text_patch import apply_exact_replacements, normalize_text_replacements, optional_bool
from ..storage import StateStore
from .filesystem import SkillFile, load_skill_file, load_skill_metadata, scan_skill_files


_WORKSPACE_SKILL_ROOTS = (
    (".mnemo", "skills"),
    (".agents", "skills"),
    (".claude", "skills"),
    (".hermes", "skills"),
    (".openclaw", "skills"),
)
_HOME_SKILL_ROOTS = (
    (".claude", "skills"),
    (".hermes", "skills"),
    (".openclaw", "skills"),
)
_CLAWHUB_DOWNLOAD_BASE = "https://wry-manatee-359.convex.site/api/v1/download"
_MAX_SKILL_SOURCE_BYTES = 25 * 1024 * 1024


class SkillService:
    def __init__(self, store: StateStore, roots: list[str | Path] | None = None):
        self.store = store
        self.roots = [Path(root).expanduser() for root in roots or []]

    def scan(self) -> list[dict[str, Any]]:
        scanned = scan_skill_files(self.roots)
        for skill in scanned:
            self.store.upsert_skill(
                skill.name,
                skill.description,
                skill.body,
                source=f"file:{skill.path}",
                status="active",
                path=str(skill.path),
            )
        return [_skill_file_as_dict(skill) for skill in scanned]

    def list(self) -> list[dict[str, Any]]:
        return self.store.list_skills()

    def context_cards(self, limit: int = 12) -> list[dict[str, Any]]:
        skills = self.store.list_skills()
        usage_stats = _skill_usage_stats(self.store)
        ranked = sorted(skills, key=lambda skill: _skill_rank(skill, usage_stats))
        return [_skill_context_card(skill, usage_stats.get(skill["name"])) for skill in ranked[:limit]]

    def view(self, name: str) -> dict[str, Any] | None:
        return self.store.get_skill(name)

    def install(self, source: str | Path, *, force: bool = False) -> dict[str, Any]:
        source_text = str(source).strip()
        if not source_text:
            raise ValueError("Skill source is required")

        with _materialized_skill_source(source_text) as (source_path, source_label):
            installables = _installable_skills(source_path)
            if not installables:
                raise ValueError(f"No SKILL.md files found in skill source: {source_text}")
            _validate_installable_names(installables)

            target_root = self.store.state_dir / "skills" / "_installed"
            for skill, _copy_root, _file_only in installables:
                existing = self.store.get_skill(skill.name)
                if existing and not force:
                    raise ValueError(f"Skill already exists: {skill.name}")
                target_dir = target_root / _slug(skill.name)
                if target_dir.exists() and not force:
                    raise ValueError(f"Installed skill target already exists: {target_dir}")

            installed: list[dict[str, Any]] = []
            for skill, copy_root, file_only in installables:
                target_dir = target_root / _slug(skill.name)
                target_path = target_dir / "SKILL.md"
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                target_dir.mkdir(parents=True, exist_ok=True)
                if file_only:
                    shutil.copy2(skill.path, target_path)
                else:
                    _copy_skill_tree(copy_root, target_dir)

                skill_id = self.store.upsert_skill(
                    skill.name,
                    skill.description,
                    skill.body,
                    source=f"installed:{source_label}",
                    status="active",
                    path=str(target_path),
                )
                installed.append(
                    {
                        "skill_id": skill_id,
                        "name": skill.name,
                        "description": skill.description,
                        "status": "active",
                        "path": str(target_path),
                        "source": source_text,
                    }
                )

            return {
                "kind": "skill_install_result",
                "source": source_text,
                "target_root": str(target_root),
                "count": len(installed),
                "skills": installed,
            }

    def run_eval_case(self, case_id: str) -> dict[str, Any]:
        eval_case = self.store.get_eval_case(case_id)
        if not eval_case:
            raise ValueError(f"Eval case not found: {case_id}")

        case = eval_case.get("case") or {}
        skill_name = _eval_case_skill_name(case)
        assertions: list[dict[str, Any]] = []
        errors: list[str] = []
        skill = self.store.get_skill(skill_name) if skill_name else None
        if not skill_name:
            errors.append("missing_skill_target")
        elif not skill:
            errors.append("skill_not_found")
        else:
            assertions, errors = _run_skill_assertions(skill, case)

        passed = not errors
        status = "passed" if passed else "failed"
        result = {
            "ok": passed,
            "skill_name": skill_name,
            "errors": errors,
            "assertions": assertions,
        }
        self.store.update_eval_case_status(case_id, status, result=result)
        return {
            "case_id": case_id,
            "skill_name": skill_name,
            "status": status,
            "passed": passed,
            "errors": errors,
            "assertions": assertions,
        }

    def crystallize_from_run(
        self,
        run_id: str,
        name: str,
        *,
        description: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        trace = self.store.get_run_events(run_id)
        if not trace:
            raise ValueError(f"Run not found: {run_id}")
        if not _run_completed(trace):
            raise ValueError(f"Run is not completed: {run_id}")

        tool_results = _compact_successful_tool_results(trace)
        if not tool_results:
            raise ValueError(f"Run has no successful tool results: {run_id}")

        skill_name = name.strip()
        if not skill_name:
            raise ValueError("Skill name is required")
        skill_description = (description or f"Crystallized SOP from run {run_id}").strip()
        body = _crystallized_skill_body(
            run_id=run_id,
            name=skill_name,
            description=skill_description,
            tool_results=tool_results,
            notes=notes,
        )
        skill_id = self.store.upsert_skill(
            skill_name,
            skill_description,
            body,
            source=f"run:{run_id}:crystallized",
            status="draft",
        )
        return {
            "skill_id": skill_id,
            "name": skill_name,
            "description": skill_description,
            "status": "draft",
            "source_run_id": run_id,
            "tool_names": _unique_tool_names(tool_results),
        }

    def patch_candidate(
        self,
        source_name: str,
        name: str,
        replacements: Any,
        *,
        description: str | None = None,
        replace_all: Any = False,
    ) -> dict[str, Any]:
        source_name = source_name.strip()
        candidate_name = name.strip()
        if not source_name:
            raise ValueError("Source skill name is required")
        if not candidate_name:
            raise ValueError("Patch candidate name is required")
        if candidate_name == source_name:
            raise ValueError("Patch candidate name must differ from source skill name")

        source = self.store.get_skill(source_name)
        if not source:
            raise ValueError(f"Skill not found: {source_name}")
        existing_candidate = self.store.get_skill(candidate_name)
        if existing_candidate and existing_candidate.get("status") == "active":
            raise ValueError(f"Patch candidate name already active: {candidate_name}")

        normalized_replacements = normalize_text_replacements(replacements)
        replace_all_value = optional_bool(replace_all, default=False)
        body = str(source.get("body") or "")
        updated_body, applied = apply_exact_replacements(
            body,
            normalized_replacements,
            replace_all=replace_all_value,
        )
        if updated_body == body:
            raise ValueError("Patch did not change the skill body")

        skill_description = (description or source.get("description") or "").strip()
        skill_id = self.store.upsert_skill(
            candidate_name,
            skill_description,
            updated_body,
            source=f"skill:{source_name}:patch",
            status="draft",
        )
        return {
            "skill_id": skill_id,
            "name": candidate_name,
            "source_skill": source_name,
            "status": "draft",
            "replacements": applied,
            "replace_all": replace_all_value,
            "body_chars": len(updated_body),
        }

    def review(self, name: str) -> dict[str, Any]:
        skill = self.store.get_skill(name)
        if not skill:
            raise ValueError(f"Skill not found: {name}")

        usage = _skill_usage_stats(self.store).get(name, {})
        eval_cases = self.store.list_eval_cases(skill_name=name, limit=100)
        eval_summary = _skill_eval_summary(eval_cases)
        if skill.get("status") == "active":
            return {
                "name": name,
                "status": "active",
                "errors": [],
                "usage": _compact_usage(usage),
                "evals": eval_summary,
                "reason": "already_active",
            }

        errors = _skill_review_errors(skill, usage)
        errors.extend(_skill_eval_errors(eval_summary))
        errors = list(dict.fromkeys(errors))
        status = "ready" if not errors else f"blocked:{errors[0]}"
        self.store.update_skill_status(name, status)
        return {
            "name": name,
            "status": status,
            "errors": errors,
            "usage": _compact_usage(usage),
            "evals": eval_summary,
        }

    def promote(self, name: str) -> dict[str, Any]:
        skill = self.store.get_skill(name)
        if not skill:
            raise ValueError(f"Skill not found: {name}")

        target_dir = self.store.state_dir / "skills" / "_generated" / _slug(name)
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / "SKILL.md"
        target_path.write_text(_skill_markdown(skill), encoding="utf-8")
        self.store.update_skill_status(name, "active", source="generated", path=str(target_path))
        promoted = self.store.get_skill(name) or skill
        return {
            "name": name,
            "path": str(target_path),
            "skill": promoted,
        }


def default_skill_roots(
    state_dir: str | Path,
    workspace: str | Path | None = None,
    home: str | Path | None = None,
) -> list[Path]:
    workspace_path = Path(workspace or Path.cwd()).expanduser()
    state_path = Path(state_dir).expanduser()
    home_path = Path.home().expanduser() if home is None else Path(home).expanduser()
    roots = [state_path / "skills"]
    roots.extend(workspace_path.joinpath(*parts) for parts in _WORKSPACE_SKILL_ROOTS)
    roots.extend(home_path.joinpath(*parts) for parts in _HOME_SKILL_ROOTS)
    return _dedupe_paths(roots)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _path_key(path: Path) -> str:
    try:
        return str(path.expanduser().resolve(strict=False))
    except OSError:
        return str(path.expanduser())


@contextmanager
def _materialized_skill_source(source: str) -> Iterator[tuple[Path, str]]:
    path = Path(source).expanduser()
    if path.exists():
        yield path, source
        return

    clawhub_slug = _clawhub_slug_from_source(source)
    if clawhub_slug:
        with tempfile.TemporaryDirectory(prefix="mnemo-skill-clawhub-") as tmp:
            extracted = _download_and_extract_skill_archive(
                _clawhub_download_url(clawhub_slug),
                Path(tmp),
                error_prefix="Failed to download ClawHub skill",
            )
            yield extracted, f"clawhub:{clawhub_slug}"
        return

    if _looks_like_archive_source(source):
        with tempfile.TemporaryDirectory(prefix="mnemo-skill-archive-") as tmp:
            extracted = _download_and_extract_skill_archive(
                source,
                Path(tmp),
                error_prefix="Failed to download skill archive",
            )
            yield extracted, f"archive:{source}"
        return

    if _looks_like_url_source(source) and _looks_like_direct_skill_url(source):
        with tempfile.TemporaryDirectory(prefix="mnemo-skill-url-") as tmp:
            materialized = _download_generic_skill_source(source, Path(tmp))
            yield materialized, f"url:{source}"
        return

    if _looks_like_git_source(source):
        git = shutil.which("git")
        if not git:
            raise ValueError("git is required to install remote skill sources")

        with tempfile.TemporaryDirectory(prefix="mnemo-skill-install-") as tmp:
            target = Path(tmp) / "repo"
            result = subprocess.run(
                [git, "clone", "--depth", "1", source, str(target)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                detail = _compact_text(result.stderr or result.stdout, limit=300)
                raise ValueError(f"Failed to clone skill source: {detail}")
            yield target, f"git:{source}"
        return

    if _looks_like_url_source(source):
        with tempfile.TemporaryDirectory(prefix="mnemo-skill-url-") as tmp:
            materialized = _download_generic_skill_source(source, Path(tmp))
            yield materialized, f"url:{source}"
        return

    raise ValueError(f"Skill source not found: {source}")


def _looks_like_git_source(source: str) -> bool:
    text = source.strip()
    if text.startswith("git@") or text.endswith(".git"):
        return True
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme in {"ssh", "git"}:
        return True
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.netloc.casefold() in {"raw.githubusercontent.com"}:
        return False
    path = parsed.path.casefold()
    if "/blob/" in path or "/raw/" in path or "/-/blob/" in path or "/-/raw/" in path:
        return False
    return parsed.netloc.casefold() in {"github.com", "gitlab.com", "bitbucket.org"}


def _clawhub_slug_from_source(source: str) -> str:
    text = source.strip()
    parsed = urllib.parse.urlparse(text)
    if parsed.scheme in {"http", "https"} and parsed.netloc.casefold() == "clawhub.ai":
        parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
        if len(parts) >= 2:
            return _valid_clawhub_slug(parts[-1])
        return ""
    if "/" not in text and "\\" not in text and _valid_clawhub_slug(text):
        return text
    return ""


def _valid_clawhub_slug(value: str) -> str:
    text = value.strip()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,127}", text):
        return text
    return ""


def _clawhub_download_url(slug: str) -> str:
    return f"{_CLAWHUB_DOWNLOAD_BASE}?{urllib.parse.urlencode({'slug': slug})}"


def _looks_like_archive_source(source: str) -> bool:
    parsed = urllib.parse.urlparse(source.strip())
    if parsed.scheme not in {"http", "https", "file"}:
        return False
    return parsed.path.lower().endswith(".zip") or bool(_download_query_slug(parsed))


def _looks_like_url_source(source: str) -> bool:
    return urllib.parse.urlparse(source.strip()).scheme in {"http", "https", "file"}


def _download_query_slug(parsed: urllib.parse.ParseResult) -> str:
    values = urllib.parse.parse_qs(parsed.query).get("slug", [])
    if not values:
        return ""
    return _valid_clawhub_slug(values[0])


def _download_and_extract_skill_archive(source_url: str, temp_root: Path, *, error_prefix: str) -> Path:
    archive_path = temp_root / "skill.zip"
    extract_dir = temp_root / "extracted"
    _download_url_to_file(source_url, archive_path, error_prefix=error_prefix)

    extract_dir.mkdir(parents=True, exist_ok=True)
    _extract_zip_safely(archive_path, extract_dir)
    return extract_dir


def _download_generic_skill_source(source_url: str, temp_root: Path) -> Path:
    payload_path = temp_root / "source"
    download_url = _normalized_skill_download_url(source_url)
    content_type = _download_url_to_file(download_url, payload_path, error_prefix="Failed to download skill source")
    if _is_zip_archive(payload_path, content_type):
        extract_dir = temp_root / "extracted"
        extract_dir.mkdir(parents=True, exist_ok=True)
        _extract_zip_safely(payload_path, extract_dir)
        return extract_dir
    if _is_skill_markdown_source(source_url, payload_path, content_type):
        raw_dir = temp_root / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(payload_path, raw_dir / "SKILL.md")
        return raw_dir
    raise ValueError("Downloaded skill source is not a zip archive or SKILL.md")


def _download_url_to_file(source_url: str, target_path: Path, *, error_prefix: str) -> str:
    try:
        with urllib.request.urlopen(source_url, timeout=30) as response:
            content_type = str(response.headers.get("Content-Type") or "")
            total = 0
            with target_path.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > _MAX_SKILL_SOURCE_BYTES:
                        raise ValueError(f"{error_prefix}: source exceeds {_MAX_SKILL_SOURCE_BYTES} bytes")
                    handle.write(chunk)
            return content_type
    except urllib.error.HTTPError as exc:
        raise ValueError(f"{error_prefix}: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ValueError(f"{error_prefix}: {exc.reason}") from exc
    except OSError as exc:
        raise ValueError(f"{error_prefix}: {exc}") from exc


def _is_zip_archive(path: Path, content_type: str) -> bool:
    if "zip" in content_type.casefold():
        return True
    try:
        with path.open("rb") as handle:
            return handle.read(4).startswith(b"PK\x03\x04")
    except OSError:
        return False


def _is_skill_markdown_source(source_url: str, path: Path, content_type: str) -> bool:
    parsed = urllib.parse.urlparse(source_url)
    filename = Path(urllib.parse.unquote(parsed.path)).name.casefold()
    content_type_lower = content_type.casefold()
    if "text/" not in content_type_lower and "markdown" not in content_type_lower:
        return False
    try:
        preview = path.read_text(encoding="utf-8")[:4096]
    except (OSError, UnicodeDecodeError):
        return False
    stripped = preview.lstrip().casefold()
    if stripped.startswith("<!doctype html") or stripped.startswith("<html"):
        return False
    if filename == "skill.md":
        return True
    lines = preview.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    return any(line.strip() == "---" for line in lines[1:]) and "name:" in preview


def _looks_like_direct_skill_url(source_url: str) -> bool:
    parsed = urllib.parse.urlparse(source_url.strip())
    if parsed.scheme not in {"http", "https", "file"}:
        return False
    if parsed.scheme == "file":
        return True
    path = parsed.path.casefold()
    if path.endswith("/skill.md") or path.endswith(".md") or path.endswith(".txt"):
        return True
    return "/blob/" in path or "/raw/" in path or "/-/blob/" in path or "/-/raw/" in path


def _normalized_skill_download_url(source_url: str) -> str:
    parsed = urllib.parse.urlparse(source_url.strip())
    netloc = parsed.netloc.casefold()
    parts = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    if parsed.scheme in {"http", "https"} and netloc == "github.com" and len(parts) >= 5:
        owner, repo, marker, ref = parts[:4]
        rest = parts[4:]
        if marker in {"blob", "raw"} and rest:
            raw_path = "/".join(urllib.parse.quote(part, safe="") for part in [owner, repo, ref, *rest])
            return urllib.parse.urlunparse(("https", "raw.githubusercontent.com", f"/{raw_path}", "", "", ""))
    if parsed.scheme in {"http", "https"} and netloc.endswith("gitlab.com") and "/-/blob/" in parsed.path:
        return source_url.replace("/-/blob/", "/-/raw/", 1)
    return source_url


def _extract_zip_safely(archive_path: Path, target_dir: Path) -> None:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            target_root = target_dir.resolve()
            for member in archive.infolist():
                destination = (target_dir / member.filename).resolve()
                if destination != target_root and target_root not in destination.parents:
                    raise ValueError(f"Unsafe path in skill archive: {member.filename}")
            archive.extractall(target_dir)
    except zipfile.BadZipFile as exc:
        raise ValueError("Skill archive is not a valid zip file") from exc


def _installable_skills(source_path: Path) -> list[tuple[SkillFile, Path, bool]]:
    if source_path.is_file():
        if source_path.name != "SKILL.md":
            raise ValueError("Skill file must be named SKILL.md")
        return [(load_skill_file(source_path, source_root=source_path.parent), source_path.parent, True)]

    if not source_path.is_dir():
        raise ValueError(f"Skill source is not a file or directory: {source_path}")

    root_skill = source_path / "SKILL.md"
    if root_skill.is_file():
        return [(load_skill_file(root_skill, source_root=source_path), source_path, False)]

    return [(skill, skill.path.parent, False) for skill in scan_skill_files([source_path])]


def _validate_installable_names(installables: list[tuple[SkillFile, Path, bool]]) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for skill, _copy_root, _file_only in installables:
        if skill.name in seen:
            duplicates.add(skill.name)
        seen.add(skill.name)
    if duplicates:
        names = ", ".join(sorted(duplicates))
        raise ValueError(f"Duplicate skill names in source: {names}")


def _copy_skill_tree(source_dir: Path, target_dir: Path) -> None:
    shutil.copytree(
        source_dir,
        target_dir,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
    )


def _skill_file_as_dict(skill: SkillFile) -> dict[str, Any]:
    return {
        "name": skill.name,
        "description": skill.description,
        "body": skill.body,
        "path": str(skill.path),
        "source_root": str(skill.source_root),
        "metadata": skill.metadata,
    }


def _skill_context_card(skill: dict[str, Any], usage: dict[str, Any] | None = None) -> dict[str, Any]:
    metadata = _skill_metadata(skill)
    card = {
        "name": skill["name"],
        "description": skill.get("description", ""),
        "status": skill.get("status", "unknown"),
        "source": skill.get("source", ""),
        "path": skill.get("path"),
    }

    allowed_tools = _metadata_allowed_tools(metadata)
    if allowed_tools:
        card["allowed_tools"] = allowed_tools

    for key in ("arguments", "scope"):
        if key in metadata:
            card[key] = metadata[key]

    if not card.get("source") and "source" in metadata:
        card["source"] = metadata["source"]
    if not card.get("path") and "path" in metadata:
        card["path"] = metadata["path"]

    if usage:
        card["usage"] = {
            "uses": usage.get("uses", 0),
            "views": usage.get("views", 0),
            "outcomes": usage.get("outcomes", 0),
            "successes": usage.get("successes", 0),
            "failures": usage.get("failures", 0),
            "avg_score": round(float(usage.get("avg_score", 0.0)), 3),
        }

    return card


def _skill_usage_stats(store: StateStore) -> dict[str, dict[str, Any]]:
    stats = getattr(store, "skill_usage_stats", None)
    if not stats:
        return {}
    return stats()


def _skill_rank(skill: dict[str, Any], stats: dict[str, dict[str, Any]]) -> tuple[float, int, int, str]:
    usage = stats.get(skill["name"], {})
    return (
        -float(usage.get("avg_score", 0.0)),
        -int(usage.get("successes", 0)),
        -int(usage.get("uses", 0)),
        str(skill["name"]),
    )


def _skill_review_errors(skill: dict[str, Any], usage: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    name = str(skill.get("name") or "").strip()
    description = str(skill.get("description") or "").strip()
    body = str(skill.get("body") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{1,63}", name):
        errors.append("invalid_name")
    if len(description) < 8:
        errors.append("missing_description")
    if len(body) < 20:
        errors.append("body_too_short")
    if int(usage.get("outcomes", 0)) > 0 and float(usage.get("avg_score", 0.0)) < 0:
        errors.append("negative_usage")
    if int(usage.get("failures", 0)) > int(usage.get("successes", 0)) and int(usage.get("successes", 0)) == 0:
        errors.append("negative_usage")
    return list(dict.fromkeys(errors))


def _eval_case_skill_name(case: dict[str, Any]) -> str:
    for key in ("skill_name", "skill_candidate", "skill", "name"):
        value = case.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _run_skill_assertions(skill: dict[str, Any], case: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    body = str(skill.get("body") or "")
    description = str(skill.get("description") or "")
    assertions: list[dict[str, Any]] = []
    errors: list[str] = []
    payload = _assertion_payload(case)

    for expected in _string_list(payload.get("body_contains")):
        passed = expected in body
        assertions.append({"name": "body_contains", "value": expected, "passed": passed})
        if not passed:
            errors.append("body_missing_text")

    for expected in _string_list(payload.get("description_contains")):
        passed = expected in description
        assertions.append({"name": "description_contains", "value": expected, "passed": passed})
        if not passed:
            errors.append("description_missing_text")

    for forbidden in [*_string_list(payload.get("body_not_contains")), *_string_list(payload.get("body_forbids"))]:
        passed = forbidden not in body
        assertions.append({"name": "body_not_contains", "value": forbidden, "passed": passed})
        if not passed:
            errors.append("body_forbidden_text")

    min_chars = payload.get("min_body_chars")
    if min_chars is not None:
        try:
            min_value = int(min_chars)
        except (TypeError, ValueError):
            min_value = -1
        passed = min_value >= 0 and len(body.strip()) >= min_value
        assertions.append({"name": "min_body_chars", "value": min_chars, "passed": passed})
        if not passed:
            errors.append("body_too_short")

    return assertions, list(dict.fromkeys(errors))


def _assertion_payload(case: dict[str, Any]) -> dict[str, Any]:
    assertions = case.get("assertions")
    if isinstance(assertions, dict):
        return {**case, **assertions}
    return case


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _skill_eval_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [case["id"] for case in cases if case.get("status") == "passed"]
    failed = [case["id"] for case in cases if case.get("status") == "failed"]
    pending = [case["id"] for case in cases if case.get("status") not in {"passed", "failed"}]
    return {
        "total": len(cases),
        "passed": len(passed),
        "failed": len(failed),
        "pending": len(pending),
        "passed_eval_case_ids": passed,
        "failed_eval_case_ids": failed,
        "pending_eval_case_ids": pending,
    }


def _skill_eval_errors(summary: dict[str, Any]) -> list[str]:
    if int(summary.get("failed", 0)) > 0:
        return ["failed_eval"]
    if int(summary.get("total", 0)) > 0 and int(summary.get("passed", 0)) == 0:
        return ["missing_eval"]
    return []


def _run_completed(trace: list[dict[str, Any]]) -> bool:
    completed = False
    for event in trace:
        if event.get("event_type") != "run.completed":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict):
            completed = True
            continue
        completed = completed or str(payload.get("status") or "completed") == "completed"
    return completed


def _compact_successful_tool_results(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for event in trace:
        if event.get("event_type") != "tool.result":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or not payload.get("ok"):
            continue
        tool_name = str(payload.get("tool_name") or "").strip()
        if not tool_name or tool_name == "skill_crystallize_from_run":
            continue
        results.append(
            {
                "tool_name": tool_name,
                "summary": _compact_text(payload.get("summary") or "Tool call completed.", limit=200),
                "evidence_count": _evidence_count(payload.get("evidence")),
            }
        )
    return results


def _crystallized_skill_body(
    *,
    run_id: str,
    name: str,
    description: str,
    tool_results: list[dict[str, Any]],
    notes: str | None = None,
) -> str:
    tool_names = _unique_tool_names(tool_results)
    lines = [
        "# Purpose",
        description,
        "",
        "# Procedure",
        "1. Start from the user's current goal and relevant mission context.",
    ]
    for index, tool_name in enumerate(tool_names, start=2):
        lines.append(f"{index}. Use `{tool_name}` when the task state calls for the same capability.")
    lines.extend(
        [
            f"{len(tool_names) + 2}. Return concise progress and cite compact evidence, not raw payloads.",
            "",
            "# Source Run Evidence",
            f"- source_run_id: `{run_id}`",
            f"- draft_skill: `{name}`",
            f"- tools: {', '.join(f'`{tool_name}`' for tool_name in tool_names)}",
            "- compact tool summaries:",
        ]
    )
    for result in tool_results:
        lines.append(
            f"  - `{result['tool_name']}`: {result['summary']} "
            f"(evidence_items={result['evidence_count']})"
        )
    lines.extend(
        [
            "",
            "# Review Notes",
            _compact_text(notes, limit=800) if notes else "Review and test this draft before promotion.",
        ]
    )
    return "\n".join(lines).strip()


def _unique_tool_names(tool_results: list[dict[str, Any]]) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for result in tool_results:
        name = str(result.get("tool_name") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _evidence_count(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _compact_text(value: Any, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _compact_usage(usage: dict[str, Any]) -> dict[str, Any]:
    return {
        "uses": int(usage.get("uses", 0)),
        "outcomes": int(usage.get("outcomes", 0)),
        "successes": int(usage.get("successes", 0)),
        "failures": int(usage.get("failures", 0)),
        "avg_score": round(float(usage.get("avg_score", 0.0)), 3),
    }


def _skill_metadata(skill: dict[str, Any]) -> dict[str, Any]:
    metadata = skill.get("metadata")
    if isinstance(metadata, dict):
        return metadata

    path = skill.get("path")
    if not path:
        return {}
    return load_skill_metadata(path)


def _metadata_allowed_tools(metadata: dict[str, Any]) -> list[str]:
    value = metadata.get("allowed_tools", metadata.get("allowed-tools", []))
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    if isinstance(value, str) and value:
        return [value]
    return []


def _skill_markdown(skill: dict[str, Any]) -> str:
    return "\n".join(
        [
            "---",
            f"name: {skill['name']}",
            f"description: {skill.get('description', '')}",
            "---",
            "",
            skill.get("body", "").strip(),
            "",
        ]
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return slug or "skill"
