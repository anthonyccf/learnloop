"""Owner-scoped shared prompt templates."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from learnloop.core.prompt_versions import builtin_prompts
from learnloop.persistence.database import AgentTemplate, AgentTemplateDefault


class Template(BaseModel):
    id: str = Field(min_length=1, max_length=36)
    agent: Literal["expert", "tutor", "assessing"]
    name: str = Field(min_length=1, max_length=200)
    prompts: dict[str, str]
    enabledTools: list[str]
    model: str
    temperature: float | None
    basePrompts: Literal["v1", "v2"] = "v1"
    createdAt: str
    updatedAt: str
    isDefault: bool = False

class Mutation(BaseModel):
    template: Template
    importOnly: bool = False

class TemplateId(BaseModel):
    id: str

def build_router(context):
    router = APIRouter(tags=["Agent templates"])

    @router.get("/api/agent-templates/builtin-prompts")
    def list_builtin_prompts(
        agent: Literal["expert", "tutor", "assessing"],
        version: Literal["v1", "v2"] = "v1",
        owner=Depends(context.owner),
    ):
        del owner
        return builtin_prompts(agent, version)

    @router.get("/api/agent-templates")
    def list_templates(owner=Depends(context.owner)):
        with context.factory() as db:
            defaults = {d.agent: d.template_id for d in db.scalars(select(AgentTemplateDefault).where(AgentTemplateDefault.owner_id == owner))}
            return [{**t.data, "isDefault": defaults.get(t.agent) == t.id} for t in db.scalars(select(AgentTemplate).where(AgentTemplate.owner_id == owner))]

    @router.post("/api/agent-templates/save")
    def save(body: Mutation, owner=Depends(context.owner)):
        template = body.template
        if not all(key in template.prompts for key in ("analysis", "lesson", "questions")):
            raise HTTPException(422, "All prompt stages are required.")
        with context.factory.begin() as db:
            item = db.get(AgentTemplate, template.id)
            if item and item.owner_id != owner:
                raise HTTPException(404, "Template not found.")
            if item and body.importOnly:
                return {"ok": True}
            if item and item.agent != template.agent:
                raise HTTPException(422, "A template cannot change agent.")
            data = template.model_dump(exclude={"isDefault"})
            if item:
                item.data = data
            else:
                item = AgentTemplate(id=template.id, owner_id=owner, agent=template.agent, data=data)
                db.add(item)
                db.flush()
            default = db.get(AgentTemplateDefault, (owner, template.agent))
            if template.isDefault:
                if default:
                    default.template_id = item.id
                else:
                    db.add(AgentTemplateDefault(owner_id=owner, agent=template.agent, template_id=item.id))
            elif default and default.template_id == item.id:
                db.delete(default)
        return {"ok": True}

    @router.post("/api/agent-templates/delete")
    def delete(body: TemplateId, owner=Depends(context.owner)):
        with context.factory.begin() as db:
            item = db.get(AgentTemplate, body.id)
            if not item or item.owner_id != owner:
                raise HTTPException(404, "Template not found.")
            default = db.get(AgentTemplateDefault, (owner, item.agent))
            if default and default.template_id == item.id:
                db.delete(default)
                db.flush()
            db.delete(item)
        return {"ok": True}
    return router
