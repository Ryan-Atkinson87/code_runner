from __future__ import annotations

from pathlib import Path

import pytest

from app.skills import (
    Skill,
    SkillLoadError,
    SkillStage,
    load_and_merge,
    load_skills_from_directory,
    merge_skills,
)


def _write_skill(
    directory: Path,
    skill_id: str,
    stage: str = "implement",
    executor: str = "ai",
    applies_to: str = "neutral",
    specialities: str = "",
    description: str = "A test skill.",
    body: str = "Do the thing.",
) -> Path:
    skill_dir = directory / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)
    spec_lines = [
        f"id: {skill_id}",
        f"stage: {stage}",
        f"executor: {executor}",
        f"applies_to: {applies_to}",
        f"description: {description}",
    ]
    if specialities:
        spec_lines.append(f"specialities: {specialities}")
    frontmatter = "\n".join(spec_lines)
    (skill_dir / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n{body}\n")
    return skill_dir


class TestSkillModel:
    def test_minimal_skill(self) -> None:
        skill = Skill(id="test-skill", stage=SkillStage.IMPLEMENT, executor="ai")
        assert skill.id == "test-skill"
        assert skill.stage == SkillStage.IMPLEMENT
        assert skill.executor == "ai"
        assert skill.applies_to == "neutral"
        assert skill.specialities == []
        assert skill.body == ""

    def test_applies_to_provider_list(self) -> None:
        skill = Skill(
            id="claude-hooks",
            stage=SkillStage.IMPLEMENT,
            executor="ai",
            applies_to=["claude"],
        )
        assert skill.applies_to == ["claude"]

    def test_specialities_filtering(self) -> None:
        skill = Skill(
            id="wcag-check",
            stage=SkillStage.QA,
            executor="ai",
            specialities=["frontend", "accessibility"],
        )
        assert "frontend" in skill.specialities
        assert "backend" not in skill.specialities

    def test_all_stages_valid(self) -> None:
        for stage in SkillStage:
            skill = Skill(id=f"s-{stage.value}", stage=stage, executor="ai")
            assert skill.stage == stage


class TestSkillStage:
    def test_nine_stages(self) -> None:
        assert len(SkillStage) == 9

    def test_stage_values(self) -> None:
        expected = {
            "plan",
            "implement",
            "test",
            "contract-verify",
            "review",
            "qa",
            "integrate",
            "escalate",
            "cross-cutting",
        }
        assert {s.value for s in SkillStage} == expected


class TestLoadFromDirectory:
    def test_loads_base_skills(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "skill-a", stage="plan", executor="ai")
        _write_skill(tmp_path, "skill-b", stage="test", executor="engine")

        skills = load_skills_from_directory(tmp_path)
        assert len(skills) == 2
        ids = {s.id for s in skills}
        assert ids == {"skill-a", "skill-b"}

    def test_loads_body(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "my-skill", body="Step 1: do stuff.\n\nStep 2: done.")
        skills = load_skills_from_directory(tmp_path)
        assert "Step 1" in skills[0].body

    def test_missing_directory_raises(self, tmp_path: Path) -> None:
        with pytest.raises(SkillLoadError, match="does not exist"):
            load_skills_from_directory(tmp_path / "nonexistent")

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        skills = load_skills_from_directory(tmp_path)
        assert skills == []

    def test_ignores_non_skill_files(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("Not a skill")
        _write_skill(tmp_path, "real-skill")
        skills = load_skills_from_directory(tmp_path)
        assert len(skills) == 1


class TestMalformedSkills:
    def test_missing_frontmatter_raises(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("No frontmatter here.")

        with pytest.raises(SkillLoadError, match="missing YAML frontmatter"):
            load_skills_from_directory(tmp_path)

    def test_unknown_stage_raises(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "bad-stage", stage="deploy")
        with pytest.raises(SkillLoadError, match="invalid skill metadata"):
            load_skills_from_directory(tmp_path)

    def test_bad_executor_raises(self, tmp_path: Path) -> None:
        _write_skill(tmp_path, "bad-exec", executor="human")
        with pytest.raises(SkillLoadError, match="invalid skill metadata"):
            load_skills_from_directory(tmp_path)

    def test_invalid_yaml_raises(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad-yaml"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\n: invalid: yaml: {{{\n---\nBody.")

        with pytest.raises(SkillLoadError, match="invalid YAML"):
            load_skills_from_directory(tmp_path)

    def test_non_mapping_frontmatter_raises(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "list-front"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("---\n- item\n- item2\n---\nBody.")

        with pytest.raises(SkillLoadError, match="must be a YAML mapping"):
            load_skills_from_directory(tmp_path)


class TestMergeSkills:
    def test_override_replaces_by_id(self, tmp_path: Path) -> None:
        base = [
            Skill(id="s1", stage=SkillStage.PLAN, executor="ai", body="base body"),
        ]
        overrides = [
            Skill(id="s1", stage=SkillStage.PLAN, executor="ai", body="override body"),
        ]
        merged = merge_skills(base, overrides)
        assert len(merged) == 1
        assert merged[0].body == "override body"

    def test_new_id_appended(self) -> None:
        base = [
            Skill(id="s1", stage=SkillStage.PLAN, executor="ai"),
        ]
        overrides = [
            Skill(id="s2", stage=SkillStage.REVIEW, executor="ai"),
        ]
        merged = merge_skills(base, overrides)
        assert len(merged) == 2
        assert {s.id for s in merged} == {"s1", "s2"}

    def test_empty_override_returns_base(self) -> None:
        base = [Skill(id="s1", stage=SkillStage.PLAN, executor="ai")]
        merged = merge_skills(base, [])
        assert len(merged) == 1
        assert merged[0].id == "s1"


class TestLoadAndMerge:
    def test_base_only(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        _write_skill(base_dir, "skill-a", stage="plan", executor="ai")

        skills = load_and_merge(base_dir)
        assert len(skills) == 1
        assert skills[0].id == "skill-a"

    def test_with_project_overrides(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        _write_skill(base_dir, "skill-a", body="base")
        _write_skill(base_dir, "skill-b", stage="review", executor="ai")

        proj_dir = tmp_path / "project"
        proj_dir.mkdir()
        _write_skill(proj_dir, "skill-a", body="override")
        _write_skill(proj_dir, "skill-c", stage="escalate", executor="engine")

        skills = load_and_merge(base_dir, proj_dir)
        by_id = {s.id: s for s in skills}
        assert len(by_id) == 3
        assert by_id["skill-a"].body == "override"
        assert "skill-b" in by_id
        assert "skill-c" in by_id

    def test_missing_project_dir_is_noop(self, tmp_path: Path) -> None:
        base_dir = tmp_path / "base"
        base_dir.mkdir()
        _write_skill(base_dir, "skill-a")

        skills = load_and_merge(base_dir, tmp_path / "nonexistent")
        assert len(skills) == 1


class TestNeutralVsProviderAppliesTo:
    def test_neutral_default(self) -> None:
        skill = Skill(id="gen", stage=SkillStage.CROSS_CUTTING, executor="ai")
        assert skill.applies_to == "neutral"

    def test_single_provider(self) -> None:
        skill = Skill(
            id="claude-only",
            stage=SkillStage.IMPLEMENT,
            executor="ai",
            applies_to=["claude"],
        )
        assert skill.applies_to == ["claude"]

    def test_multiple_providers(self) -> None:
        skill = Skill(
            id="multi",
            stage=SkillStage.IMPLEMENT,
            executor="ai",
            applies_to=["codex", "gemini"],
        )
        assert skill.applies_to == ["codex", "gemini"]
        assert "claude" not in skill.applies_to
