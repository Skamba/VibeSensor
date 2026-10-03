import type { ComponentChildren } from "preact";

/** Building blocks shared by the maintenance pages (ESP flash, update, internet). */

export type Variant = "bad" | "muted" | "ok" | "warn";

export interface StatusRow {
  label: string;
  value: string;
}

export interface ReadinessItem {
  label: string;
  detail: string;
  state: "attention" | "blocked" | "ready";
}

export interface Readiness {
  title: string;
  summary: string;
  stateLabel: string;
  stateVariant: Variant;
  items: readonly ReadinessItem[];
}

export type StageState = "active" | "attention" | "done" | "upcoming";

export interface Stage {
  phase: string;
  state: StageState;
  title: string;
  detail: string;
  stateText: string;
}

export function Pill(props: {
  id?: string;
  variant: Variant;
  children: ComponentChildren;
}) {
  return (
    <span id={props.id} class="pill" data-variant={props.variant}>
      {props.children}
    </span>
  );
}

export function StatusGrid(props: { rows: readonly StatusRow[] }) {
  return (
    <div class="status-grid">
      {props.rows.map((row) => (
        <div class="status-grid__row" key={`${row.label}:${row.value}`}>
          <span class="status-grid__label">{row.label}</span>
          <span>{row.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Note(props: { bad?: boolean; children: ComponentChildren }) {
  return (
    <div
      class={
        props.bad
          ? "maintenance-note maintenance-note--bad"
          : "maintenance-note"
      }
    >
      {props.children}
    </div>
  );
}

export function InlineEmpty(props: { title: string; body: string }) {
  return (
    <div class="empty-state empty-state--inline">
      <strong class="empty-state__title">{props.title}</strong>
      <span class="empty-state__body">{props.body}</span>
    </div>
  );
}

export function Card(props: {
  title: string;
  subtitle?: string;
  badge?: ComponentChildren;
  hero?: boolean;
  children: ComponentChildren;
}) {
  return (
    <section
      class={
        props.hero
          ? "maintenance-card maintenance-card--hero"
          : "maintenance-card"
      }
    >
      <div class="maintenance-card__header">
        <div>
          <div class="maintenance-card__title">{props.title}</div>
          {props.subtitle ? <div class="subtle">{props.subtitle}</div> : null}
        </div>
        {props.badge}
      </div>
      {props.children}
    </section>
  );
}

export function ReadinessPanel(props: { model: Readiness }) {
  const { model } = props;
  return (
    <section class="maintenance-readiness">
      <div class="maintenance-readiness__header">
        <div class="maintenance-readiness__heading">
          <div class="maintenance-readiness__title">{model.title}</div>
          <div class="maintenance-readiness__summary">{model.summary}</div>
        </div>
        {model.stateLabel ? (
          <Pill variant={model.stateVariant}>{model.stateLabel}</Pill>
        ) : null}
      </div>
      <ul class="maintenance-readiness__list">
        {model.items.map((item, index) => (
          <li
            key={`${item.label}:${index}`}
            class="maintenance-readiness__item"
            data-readiness-state={item.state}
          >
            <span aria-hidden="true" class="maintenance-readiness__marker">
              {item.state === "ready" ? "✓" : "!"}
            </span>
            <div class="maintenance-readiness__body">
              <div class="maintenance-readiness__label">{item.label}</div>
              <div class="maintenance-readiness__detail">{item.detail}</div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function StageList(props: { stages: readonly Stage[] }) {
  return (
    <ol class="maintenance-stage-list">
      {props.stages.map((stage, index) => (
        <li
          key={stage.phase}
          class="maintenance-stage"
          data-stage-phase={stage.phase}
          data-stage-state={stage.state}
          aria-current={stage.state === "active" ? "step" : undefined}
        >
          <span class="maintenance-stage__marker">
            {stage.state === "done" ? "✓" : `${index + 1}`}
          </span>
          <div class="maintenance-stage__body">
            <div class="maintenance-stage__title">{stage.title}</div>
            <div class="maintenance-stage__detail">{stage.detail}</div>
          </div>
          <span class="maintenance-stage__state">{stage.stateText}</span>
        </li>
      ))}
    </ol>
  );
}
