import Image from "next/image";

export type LearningRole = "expert" | "tutoring" | "assessing";
export const agentNames: Record<LearningRole, string> = { expert: "Expert", tutoring: "Tutor", assessing: "Reviewer" };

export function AgentPortrait({ role, size = 48 }: { role: LearningRole; size?: number }) {
  return <Image className="learning-agent-portrait" src={`/agents/${role}.svg`} alt="" width={size} height={size} unoptimized />;
}

export function AgentTeam() {
  const descriptions = { expert: "Turns your materials into clear lessons.", tutoring: "Finds a useful next question and offers hints.", assessing: "Checks your answer and explains the reasoning." };
  return <section className="learning-agent-team" aria-label="Your learning team">{(Object.keys(agentNames) as LearningRole[]).map(role => <article key={role}><AgentPortrait role={role} size={64} /><div><h2>{agentNames[role]}</h2><p>{descriptions[role]}</p></div></article>)}</section>;
}
