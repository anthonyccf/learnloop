"use client";

import { useState } from "react";
import { agentSchemaContracts } from "@/lib/agent-schemas";
import outputSchemaData from "@/lib/agent-output-schemas.json";
import { promptStagesByAgent, workbenchAgents, type ExpertPromptStage, type WorkbenchAgent } from "@/lib/expert-templates";

export function AgentSchemaPanel({ agent }: { agent: WorkbenchAgent }) {
  const [view, setView] = useState<"overview" | "json">("overview");
  const [selectedStageId, setSelectedStageId] = useState<ExpertPromptStage>("analysis");
  const [selectedOutputName, setSelectedOutputName] = useState("");
  const agentLabel = workbenchAgents.find((item) => item.id === agent)!.label;
  const stages = promptStagesByAgent[agent];
  const contracts = agentSchemaContracts[agent];
  const selectedContract = contracts.find((item) => item.id === selectedStageId) || contracts[0];
  const schemaIndex = outputSchemaData as unknown as Record<string, Record<string, Record<string, unknown>>>;
  const outputSchemas = schemaIndex[`${agent}.${selectedContract.id}`] || {};
  const outputSchemaNames = Object.keys(outputSchemas);
  const outputSchemaName = outputSchemaNames.includes(selectedOutputName) ? selectedOutputName : outputSchemaNames[0];
  const outputSchema = outputSchemaName ? outputSchemas[outputSchemaName] : null;

  return <section className="expert-schema-panel" aria-label={`${agentLabel} input and output schemas`}>
    <div className="expert-schema-intro">
      <strong>Backend contracts · read only</strong>
      <p>These are production contract summaries. Input payloads are assembled in code and are not separately validated against a JSON Schema. Prompts and settings edited here remain experiment-only.</p>
    </div>
    <div className="expert-schema-view-tabs" role="tablist" aria-label="Schema view">
      <button type="button" role="tab" aria-selected={view === "overview"} onClick={() => setView("overview")}>Overview</button>
      <button type="button" role="tab" aria-selected={view === "json"} onClick={() => setView("json")}>JSON</button>
    </div>
    {view === "overview" ? <div className="expert-schema-stage-list">
      {contracts.map((contract) => {
        const stage = stages.find((item) => item.id === contract.id)!;
        return <article className="expert-schema-stage" key={contract.id}>
          <div className="expert-schema-stage-heading">
            <div><span>{stage.label}</span><p>{stage.description}</p></div>
            <code>{contract.outputSchema}</code>
          </div>
          <div className="expert-schema-columns">
            <div className="expert-schema-column">
              <h3>Input</h3>
              <ul>{contract.input.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
            <div className="expert-schema-column">
              <h3>Output</h3>
              <ul>{contract.output.map((item) => <li key={item}>{item}</li>)}</ul>
            </div>
          </div>
        </article>;
      })}
    </div> : <>
      <div className="expert-schema-stage-tabs" role="tablist" aria-label={`${agentLabel} schema stages`}>
        {contracts.map((contract) => <button type="button" role="tab" key={contract.id} aria-selected={selectedContract.id === contract.id} onClick={() => { setSelectedStageId(contract.id); setSelectedOutputName(""); }}>{stages.find((item) => item.id === contract.id)!.label}</button>)}
      </div>
      <div className="expert-schema-json-list">
        <section className="expert-schema-json-card" aria-labelledby="expert-schema-input-json-title">
          <div className="expert-schema-json-heading"><div><h3 id="expert-schema-input-json-title">Input JSON · assembled payload shape</h3><p>{selectedContract.inputNote || "Representative payload with placeholders; actual values come from the current run."}</p></div></div>
          {selectedContract.inputExample ? <pre>{JSON.stringify(selectedContract.inputExample, null, 2)}</pre> : <p className="expert-schema-json-note">{selectedContract.inputNote || "No separate model input object is used for this stage."}</p>}
        </section>
        <section className="expert-schema-json-card" aria-labelledby="expert-schema-output-json-title">
          <div className="expert-schema-json-heading"><div><h3 id="expert-schema-output-json-title">Output JSON Schema</h3><p>{agent === "assessing" && selectedContract.id === "lesson" ? "The shared Assessment response schema; feedback is not a separate model call." : "The strict schema sent with the production model request, where this stage has one."}</p></div>
            {outputSchemaNames.length > 1 && <label className="expert-schema-format-select">Format<select value={outputSchemaName} onChange={(event) => setSelectedOutputName(event.target.value)}>{outputSchemaNames.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>}
          </div>
          {outputSchema ? <pre>{JSON.stringify(outputSchema, null, 2)}</pre> : <p className="expert-schema-json-note">{selectedContract.output[0]}</p>}
        </section>
      </div>
    </>}
  </section>;
}
