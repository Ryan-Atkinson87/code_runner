from __future__ import annotations

from pathlib import Path

import pytest

from app.profile import (
    ExecutionProfile,
    PersonaEntry,
    PersonaType,
    ProfileLoadError,
    load_execution_profile,
)

TRIVE_YAML = """\
personas:
  - type: planner
  - type: implementor
    speciality: backend
  - type: implementor
    speciality: frontend
  - type: implementor
    speciality: admin
  - type: reviewer
    speciality: backend
  - type: reviewer
    speciality: frontend
  - type: reviewer
    speciality: admin
  - type: qa-reviewer
    speciality: accessibility
  - type: qa-reviewer
    speciality: responsiveness
  - type: qa-reviewer
    speciality: ui-ux

routing:
  - persona: "reviewer×backend"
    repos: [orchestrator-api]

qa_specialities:
  - accessibility
  - responsiveness
  - ui-ux
"""

BACKEND_ONLY_YAML = """\
personas:
  - type: planner
  - type: implementor
    speciality: backend
  - type: reviewer
    speciality: backend
  - type: reviewer
    speciality: security
"""


class TestTriveShape:
    def test_loads_trive_profile(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text(TRIVE_YAML)
        profile = load_execution_profile(path)
        assert len(profile.personas) == 10

    def test_trive_qa_specialities(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text(TRIVE_YAML)
        profile = load_execution_profile(path)
        assert set(profile.qa_specialities) == {
            "accessibility",
            "responsiveness",
            "ui-ux",
        }

    def test_trive_routing(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text(TRIVE_YAML)
        profile = load_execution_profile(path)
        assert len(profile.routing) == 1
        assert profile.routing[0].repos == ["orchestrator-api"]


class TestBackendOnlyShape:
    def test_loads_backend_only(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text(BACKEND_ONLY_YAML)
        profile = load_execution_profile(path)
        assert len(profile.personas) == 4

    def test_no_qa_specialities(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text(BACKEND_ONLY_YAML)
        profile = load_execution_profile(path)
        assert profile.qa_specialities == []

    def test_no_routing(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text(BACKEND_ONLY_YAML)
        profile = load_execution_profile(path)
        assert profile.routing == []


class TestPersonaEntry:
    def test_key_with_speciality(self) -> None:
        p = PersonaEntry(type=PersonaType.IMPLEMENTOR, speciality="backend")
        assert p.key == "implementor×backend"

    def test_key_without_speciality(self) -> None:
        p = PersonaEntry(type=PersonaType.PLANNER)
        assert p.key == "planner"

    def test_all_persona_types(self) -> None:
        assert len(PersonaType) == 5
        expected = {"planner", "implementor", "reviewer", "qa-reviewer", "tech-lead"}
        assert {t.value for t in PersonaType} == expected


class TestValidation:
    def test_invalid_persona_type_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text("personas:\n  - type: coder\n")
        with pytest.raises(ProfileLoadError, match="Profile validation failed"):
            load_execution_profile(path)

    def test_empty_personas_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text("personas: []\n")
        with pytest.raises(ProfileLoadError, match="Profile validation failed"):
            load_execution_profile(path)

    def test_missing_personas_key_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text("routing: []\n")
        with pytest.raises(ProfileLoadError, match="Profile validation failed"):
            load_execution_profile(path)

    def test_malformed_yaml_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text("{{{invalid yaml")
        with pytest.raises(ProfileLoadError, match="Invalid YAML"):
            load_execution_profile(path)

    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ProfileLoadError, match="not found"):
            load_execution_profile(tmp_path / "missing.yaml")

    def test_non_mapping_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text("- item\n- item2\n")
        with pytest.raises(ProfileLoadError, match="YAML mapping"):
            load_execution_profile(path)


class TestStageOverrides:
    def test_stage_override(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text("""\
personas:
  - type: planner
stage_overrides:
  - stage: test
    executor: ai
""")
        profile = load_execution_profile(path)
        assert len(profile.stage_overrides) == 1
        assert profile.stage_overrides[0].stage == "test"
        assert profile.stage_overrides[0].executor == "ai"

    def test_invalid_executor_raises(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text("""\
personas:
  - type: planner
stage_overrides:
  - stage: test
    executor: manual
""")
        with pytest.raises(ProfileLoadError, match="Profile validation failed"):
            load_execution_profile(path)


class TestSkillOverrides:
    def test_skill_override(self, tmp_path: Path) -> None:
        path = tmp_path / "execution-profile.yaml"
        path.write_text("""\
personas:
  - type: planner
skill_overrides:
  - id: custom-lint
    stage: test
    executor: engine
    body: Run custom linter.
""")
        profile = load_execution_profile(path)
        assert len(profile.skill_overrides) == 1
        assert profile.skill_overrides[0].id == "custom-lint"
        assert profile.skill_overrides[0].body == "Run custom linter."


class TestSchemaModel:
    def test_direct_construction(self) -> None:
        profile = ExecutionProfile(
            personas=[
                PersonaEntry(type=PersonaType.PLANNER),
                PersonaEntry(
                    type=PersonaType.IMPLEMENTOR,
                    speciality="backend",
                ),
            ],
        )
        assert len(profile.personas) == 2
        assert profile.stage_overrides == []
        assert profile.routing == []
        assert profile.qa_specialities == []
        assert profile.skill_overrides == []
