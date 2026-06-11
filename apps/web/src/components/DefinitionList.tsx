import type { ApiDefinition } from "../types/dashboard";

interface DefinitionListProps {
  title: string;
  definitions: ApiDefinition[];
  extra?: ApiDefinition[];
}

export function DefinitionList({
  title,
  definitions,
  extra = [],
}: DefinitionListProps) {
  const rows = [...definitions, ...extra];

  return (
    <section className="definition-panel">
      <h2>{title}</h2>
      <dl className="definition-list">
        {rows.map((definition) => (
          <div className="definition-item" key={definition.key}>
            <dt>{definition.label}</dt>
            <dd>{definition.description}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
