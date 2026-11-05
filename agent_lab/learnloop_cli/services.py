"""Local prompt overrides, role-specific models and private experiment traces."""

import hashlib
import json
import time
import tomllib
from datetime import UTC, datetime
from uuid import uuid4

from learnloop.core.errors import ServiceError
from learnloop.services.clients import Services


class GenerationClient(Services):
    """Reuse production generation/validation without allocating a vector engine."""

    def __init__(self, settings):
        self.settings = settings


class LabServices(Services):
    def __init__(self, settings, root, prompts):
        super().__init__(settings)
        self.root, self.prompts = root, prompts

    def generate(self, role, instruction, context, output):
        config_path = self.root / "agents.toml"
        config = (
            tomllib.loads(config_path.read_text(encoding="utf-8"))
            if config_path.exists()
            else {}
        )
        model = config.get(role.lower(), {}).get("model") or self.settings.llm_model
        if not isinstance(model, str) or not model.strip():
            raise ValueError(f"Invalid model setting for {role}")
        client = GenerationClient(self.settings.model_copy(update={"llm_model": model}))
        prompt_id, instruction = self.prompts.resolve(instruction)
        record = {
            "id": uuid4().hex,
            "at": datetime.now(UTC).isoformat(),
            "role": role,
            "model": model,
            "schema": output.__name__,
            "promptId": prompt_id,
            "promptSha256": hashlib.sha256(instruction.encode()).hexdigest(),
            "instruction": instruction,
            "context": context,
        }
        started = time.monotonic()
        try:
            result = client.generate(role, instruction, context, output)
            record["output"] = result.model_dump(mode="json")
            record["status"] = "completed"
            return result
        except Exception as error:
            record["status"] = "failed"
            # Provider bodies, raw exception strings and credentials never enter traces.
            record["error"] = (
                error.code if isinstance(error, ServiceError) else type(error).__name__
            )
            raise
        finally:
            record["durationSeconds"] = round(time.monotonic() - started, 3)
            directory = self.root / "data/traces"
            directory.mkdir(parents=True, exist_ok=True)
            (directory / f"{record['id']}.json").write_text(
                json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8"
            )

    def close(self):
        if self.vectors is not None:
            self.vectors.engine.dispose()
