"""Skill system.

Skills are NOT agents — they are reusable instruction/capability
bundles that shape how the Agent approaches a task (e.g. "python",
"git", "debugging"). Each skill lives as a JSON file under
neo_code/skills/<id>/skill.json.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class Skill:
    id: str
    name: str
    description: str
    instructions: str
    capabilities: List[str] = field(default_factory=list)
    preferred_tools: List[str] = field(default_factory=list)
    examples: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            description=data.get("description", ""),
            instructions=data.get("instructions", ""),
            capabilities=data.get("capabilities", []),
            preferred_tools=data.get("preferred_tools", []),
            examples=data.get("examples", []),
            constraints=data.get("constraints", []),
            triggers=data.get("triggers", []),
        )

    def as_prompt_block(self) -> str:
        parts = [f"### Skill: {self.name}", self.instructions.strip()]
        if self.constraints:
            parts.append("Constraints: " + "; ".join(self.constraints))
        return "\n".join(parts)


class SkillLoader:
    def __init__(self, skills_dir: str):
        self.skills_dir = Path(skills_dir)
        self._skills: Dict[str, Skill] = {}
        self.reload()

    def reload(self) -> None:
        self._skills.clear()
        if not self.skills_dir.exists():
            return
        for skill_file in self.skills_dir.glob("*/skill.json"):
            try:
                data = json.loads(skill_file.read_text(encoding="utf-8"))
                skill = Skill.from_dict(data)
                self._skills[skill.id] = skill
            except (json.JSONDecodeError, OSError, KeyError):
                continue

    def all(self) -> List[Skill]:
        return list(self._skills.values())

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def relevant_to(self, text: str, project_labels: List[str], max_skills: int = 3) -> List[Skill]:
        """Very lightweight relevance ranking: trigger-keyword match
        against the user's request + detected project frameworks.
        Good enough for MVP; can be swapped for embedding-based
        retrieval later without changing the Skill data model."""
        text_l = text.lower()
        labels_l = [l.lower() for l in project_labels]
        scored = []
        for skill in self._skills.values():
            score = 0
            for trigger in skill.triggers:
                t = trigger.lower()
                if t in text_l:
                    score += 2
                if any(t in label for label in labels_l):
                    score += 1
            if score > 0:
                scored.append((score, skill))
        scored.sort(key=lambda x: -x[0])
        return [s for _, s in scored[:max_skills]]
