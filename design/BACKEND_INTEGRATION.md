# FreshRun — Backend Integration Guide

This document maps the FreshRun prototype's **mock data and client state** to the
**API endpoints and data models** the backend needs to provide. It's written for a
backend engineer wiring real services behind the existing UI.

The frontend is a React prototype (HTML + JSX, loaded via CDN). All screen logic
lives in the `*.jsx` files at the project root. **All data is currently mocked** —
defined as `FR_*` constants in JSX, or held in React state inside `app-nav.jsx`.
The goal of integration is to replace those mock sources with API calls.

---

## 1. Where the data lives (mock → replace with API)

| Domain | Mock constant | File | Replace with |
|---|---|---|---|
| Activity feed (friends) | `FR_FEED` | `home-ui.jsx` | `GET /feed` |
| Nearby runs (strangers) | `FR_NEARBY` | `home-ui.jsx` | `GET /feed/nearby` |
| Run comments | `FR_COMMENTS` | `home-ui.jsx` | `GET /runs/:id/comments` |
| Weather + AI index | `FR_WEATHER` | `home-ui.jsx` | `GET /weather?lat=&lng=` |
| Activity history | `FR_ACTS` | `records-screen.jsx` | `GET /me/activities` |
| Monthly summary | `FR_MONTHLY` | `records-screen.jsx` | `GET /me/stats/monthly` |
| Monthly AI insight (premium) | `FR_INSIGHT` | `monthly-insight.jsx` | `GET /me/insights/:yyyymm` |
| My crews + mega-challenges | `FR_MY_CREWS` | `community-screen.jsx` | `GET /me/crews` |
| Nearby/discoverable crews | `FR_NEARBY_CREWS` | `community-screen.jsx` | `GET /crews/discover?region=` |
| Joinable challenges | `FR_OPEN_CHALLENGES` | `community-screen.jsx` | `GET /challenges` |
| Notifications | `FR_NOTIFS` | `notifications-screen.jsx` | `GET /me/notifications` |
| Settings defaults | `FR_SETTINGS_DEFAULTS` | `settings-screens.jsx` | `GET/PATCH /me/settings` |
| Invite candidates | `FR_INVITE_FRIENDS` | `crew-create.jsx` | `GET /me/friends` |
| KR location tree | `FR_KR_LOCATIONS` | `location-picker.jsx` | `GET /locations` (or keep static) |
| Display-name taken/profanity | `FR_TAKEN`, `FR_PROFANITY` | `auth-app.jsx` | `GET /auth/check-name?name=` |

Static/presentational constants that do **not** need a backend: `FR_LIGHT`,
`FR_DARK`, `FR_FONT` (theme tokens, `auth-ui.jsx`), `FR_ZONE_COLORS`,
`FR_AQI_COLOR`, `FR_MOODS`, `FR_DIST_RANGES`, `FR_REGION_KEYS`, `FR_PERM_DEFS`,
`FR_FB_GOOD/BAD`, `FR_FAQ`, `FR_CREW_COLORS`.

---

## 2. Client-side state & actions (in `app-nav.jsx`)

`FrAppRoot` holds the live session state and passes an `app` object to every
screen. These are the **mutations** that must become authenticated API calls:

| Action (on `app`) | What it does now | API call |
|---|---|---|
| `saveRun(run)` | prepends to `savedRuns` | `POST /me/activities` |
| `toggleBookmark(item)` | add/remove in `bookmarks` | `PUT/DELETE /me/bookmarks/:courseId` |
| `addCrew(crew)` | prepends to `createdCrews` | `POST /crews` |
| `updateCrew(id, patch)` | merges patch into a crew | `PATCH /crews/:id` |
| `logCrewRun(id, entry)` | adds run to crew feed + bumps challenge/ranking | `POST /crews/:id/runs` |
| `toggleFavCrew(id)` | add/remove in `favCrews` | `PUT/DELETE /me/crews/:id/favorite` |
| `incAiGen()` | increments weekly AI-course counter | server-enforced quota (see §5) |
| `setSetting(group, key, v)` | updates settings | `PATCH /me/settings` |

`app` also exposes read state: `displayName`, `premium` (bool), `units`
(`'km'`/`'mi'`), `theme`, `settings`, `savedRuns`, `bookmarks`, `createdCrews`,
`favCrews`, `aiGenCount`. These would be hydrated from `GET /me` on login.

> Note: `premium`, `units`, `theme` are currently driven by the Tweaks panel
> (`TWEAK_DEFAULTS` in `app-nav.jsx`) for demo toggling. In production they come
> from the user profile / subscription status.

---

## 3. Core data models

Shapes below reflect exactly what the UI reads. Keep field names or provide a
mapping layer.

### Activity (run)  — `FR_ACTS[]`, `saveRun`, Activity Detail
```ts
interface Activity {
  id: string;
  title: string;            // "한강 야경 러닝"
  area: string;             // start area label
  date: string;             // display date "오늘" / "5월 12일"
  when: string;             // "오늘 · 05:24"
  month: string;            // "6월" — used to group history
  dist: number;             // km (UI converts to mi when units='mi')
  dur: string;              // "26:14"
  durSec: number;
  pace: string;             // "5'02\""
  paceSec: number;
  kcal: number;
  hrAvg: number; hrMax: number;
  elevGain: number;         // meters
  seed: string;             // route-map render seed (replace w/ real polyline)
  tags: string[];
  best?: boolean;           // shows "best" highlight
  splits: number[];         // per-km pace seconds → pace chart
  elev: number[];           // per-km elevation gain → elevation line
  zones: { name: string; range: string; sec: number; tone: 0|1|2|3 }[]; // HR zones
  insight: string;          // AI performance note
  recovery: string;         // AI recovery advice
  fresh?: boolean;          // true = just finished, shows "Save" CTA
}
```
**Map/route:** the prototype draws routes from a string `seed`. Replace with a
real encoded polyline / GeoJSON; the map component (`FrMiniMap`/`FrCourseMap`)
is the single render point to swap.

### Feed item — `FR_FEED[]`, `FR_NEARBY[]`
```ts
interface FeedRun {
  id: string; name: string; area: string; title: string;
  dist: number; dur: string; pace: string;
  tags: string[]; ago: string; kudos: number; comments: number; seed: string;
}
```

### Crew — `FR_MY_CREWS[]`, `addCrew`, `updateCrew`
```ts
interface Crew {
  id: string;
  type: 'crew' | 'challenge';   // 'challenge' = public mega-challenge card
  owner?: boolean;              // is the current user the owner
  name: string; desc?: string;
  members: number; maxMembers?: number;
  area: string; region?: string; radius?: number;
  myRank?: number; seed: string; color?: string;
  sport?: '러닝'|'라이딩'|'워킹';
  level?: string;               // '무관'|'입문'|'중급'|'고급'
  privacy?: '공개'|'승인제'|'비공개';   // public / approval / invite-only
  days?: string[]; time?: string;       // regular run schedule
  challenge: { title: string; done: number; goal: number; days: number; none?: boolean };
  ranking: { name: string; km: number; me?: boolean }[];
  managers?: string[];          // staff display names
  perms?: Record<string, PermSet>;   // per-manager permission overrides
  announcements?: { id: string; text: string; when: string; poll?: Poll }[];
  requests?: { id: string; name: string; sub: string; when: string }[]; // 승인제 only
  feed?: { id: string; name: string; km: number; pace: string; dur: string; seed: string; when: string }[];
}
type PermSet = { notice; challenge; invite; crewRun; editInfo; kick; appoint: boolean };
interface Poll { yes: number; no: number; myVote: 'yes'|'no'|null }
```
**Permissions** (`FR_PERM_DEFS` in `community-screen.jsx`) — keys:
`notice, challenge, invite, crewRun, editInfo` (general) and `kick, appoint`
(sensitive). Enforce server-side; the UI only gates affordances.

**Privacy rules** (already enforced in UI, must be enforced server-side):
- `공개` (public): first-come join until `maxMembers`; **no** join requests.
- `승인제` (approval): join requests queue → owner accepts/declines.
- `비공개` (private): invite/link only.

### Weather — `FR_WEATHER`
```ts
interface Weather {
  area: string; condition: string; temp: number; feels: number;
  humidity: number;
  pm10: { v: number; label: string }; pm25: { v: number; label: string };
  wind: number; uv: { v: number; label: string }; rain: number;
  aiIndex: number;     // 0–100 AI running index
  tip: string;
}
```

### Monthly stat / insight — `FR_MONTHLY[]`, `FR_INSIGHT`
```ts
interface MonthlyStat {
  label: string; year: number; mn: number;     // 1–12
  distKm: number; sessions: number; pace: string; time: string;
  weeks: number[];     // per-week km → area graph
  delta: number;       // % vs last month
}
```
`FR_INSIGHT` (premium deep-dive) adds zone distribution, terrain split, pace
trend, coaching summary — see `monthly-insight.jsx`.

### Settings — `FR_SETTINGS_DEFAULTS`
```ts
interface Settings {
  profile: { name; email; birth; weight; height; gender };
  app: { lang: 'ko'|'en'; haptics; autoPause; voiceCue; keepScreen: boolean };
  aiCourse: { terrain; defaultDist; scenic; avoidHills; preferLoop; surface };
  weather:  { avoidDust; dustLevel; avoidHeat; heatTemp; avoidRain };
  health:   { steps; workouts; heartRate; sleep; vo2 };
  social:   { apple; google; instagram; strava; kakao };
}
```

---

## 4. AI course generation

Flow lives in `course-form.jsx` (input form) → `course-flow.jsx` (generating →
map result → run). The form collects:
```ts
interface CourseRequest {
  dist: number;            // target km
  shape: 'loop'|'oneway';
  moods: string[];         // 경치/도심/자연/언덕/평지
  start: { label: string; lat?; lng? };
  advanced?: { difficulty; waypoints; avoid };
}
```
Endpoint: `POST /courses/generate` → returns a route (polyline + stats +
title + tags). The existing backend in `uploads/Running AI/` already has a
`route_service` / `openai_service` — this is the integration point.

---

## 5. Premium / quota rules (enforce server-side)

- **AI course generation** is metered: free (Lite) users get **3 generations per
  week**. The UI calls `incAiGen()` on each generate and the project spec caps at
  3/week — the server must be the source of truth (`429` when exceeded).
- **Crew creation** is **Premium-only** (`POST /crews` should reject Lite users).
- **Monthly AI insight** (`monthly-insight.jsx`) is Premium-only.
- Premium status comes from the subscription record, surfaced as `app.premium`.

---

## 6. Auth

`auth-app.jsx` / `auth-screens.jsx` handle welcome → sign up → email verify →
display-name → success. Backend needs:
- `POST /auth/signup`, `POST /auth/login`, email verification.
- `GET /auth/check-name?name=` — uniqueness + profanity (mock: `FR_TAKEN`,
  `FR_PROFANITY`). Name rule: `/^[A-Za-z0-9_가-힣]+$/`, length ≥ 2.
- On success, hydrate the `app` session state (see §2).

---

## 7. File map (frontend)

- `FreshRun App.html` — entry point; loads all JSX via `<script>` tags (load order matters).
- `app-nav.jsx` — root, tab/overlay router, **all session state & mutations**.
- `auth-*.jsx` — onboarding/auth.
- `home-ui.jsx`, `home-cards.jsx`, `home-screens.jsx` — Home + feed + weather.
- `community-screen.jsx` — crews, challenges, discover, crew admin (largest file).
- `crew-create.jsx` — create crew, invite, challenge create, edit.
- `course-ui.jsx`, `course-form.jsx`, `course-flow.jsx` — AI course flow.
- `records-screen.jsx`, `activity-detail.jsx`, `monthly-insight.jsx` — stats.
- `tracking-screen.jsx` — live run tracking (timer, pace, crew-run logging).
- `notifications-screen.jsx`, `profile-screen.jsx`, `settings-screens.jsx`.
- `weather-detail.jsx`, `celebrate-screens.jsx`, `run-choice.jsx`, `location-picker.jsx`.
- `i18n.jsx` — runtime KO↔EN translation layer (no backend dependency).
- `app-icons.jsx`, `ios-frame.jsx`, `tweaks-panel.jsx` — UI scaffolding.

The existing Python/Expo backend scaffold the partner is working from lives under
`uploads/Running AI/` (FastAPI `app/`, React-Native `frontend/`).
```
```
