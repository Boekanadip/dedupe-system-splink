# Nexus UI Design System

## Visual direction

Enterprise data-workspace interface: restrained, precise, operational, and optimized for reading data. Avoid using a generic KPI-card layout as the only page pattern. Workspaces use dense tables and review layouts; analytics pages use charts; configuration pages use structured forms.

## Color tokens

| Token | Hex | Use |
|---|---|---|
| Workspace navy | `#101B2D` | Sidebar and deep navigation surfaces |
| Primary blue | `#4B83F0` | Primary actions, active navigation, selected state |
| Mint | `#32A789` | Successful validation and positive outcomes |
| Amber | `#D89D3D` | Review, attention, and pending states |
| Violet | `#8A70D8` | Model and engine context |
| Red | `#CC696E` | Errors and destructive decisions |
| Canvas | `#F4F6FA` | Main application background |
| Surface | `#FFFFFF` | Cards, tables, dialogs |
| Ink | `#1D2B40` | Primary text |
| Muted | `#8190A4` | Secondary text and metadata |
| Border | `#E8EDF3` | Dividers and component outlines |

## Typography

- Display and page headings: Manrope, 700–800.
- Body, controls, tables, metadata: DM Sans, 400–700.
- IDs, run codes, and technical snippets: system monospace.

## Layout

- Fixed desktop sidebar: 246px; compact state: 76px.
- Sticky topbar: 66px desktop, 59px compact.
- Main content maximum width: 1600px.
- Main content padding: 34px desktop, 24px tablet, 14px mobile.
- Card radius: 10px; controls generally 6–8px.
- Responsive breakpoints: 1200px, 980px, 760px, and 520px.

## Status semantics

- Mint: completed / validated / connected (only when verified by backend).
- Amber: review / pending / needs mapping.
- Red: failed / error / disconnected.
- Neutral: draft / unconfigured / unknown.

A UI demo must not display a green connected state when no server-side connection check occurred. In this prototype the connection action returns `Demo checked`, not `Connected`.

## Core components

- Navigation: grouped sidebar with active-route marker and compact state.
- Page header: breadcrumb-like eyebrow, title, supporting description, contextual action.
- Metric card: one primary value, a context label, and a short comparison annotation.
- Table: semantic column labels, row action, empty state, and responsive horizontal scrolling.
- Status pill: explicit semantic state label.
- Review pair: side-by-side attribute comparison, evidence summary, and explicit decision controls.
- Processing stage: ordered step list with pending, running, and complete states.
- Modal: focused form with explanation, cancel action, and explicit submit action.
- Notification/toast: transient feedback with clear demo-mode wording.
