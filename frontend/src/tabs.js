// Tab registry. Adding a feature = a component file + one line here.
//   id:        stable key (also the panel CSS modifier: .panel--<id>)
//   label:     Czech text in the nav
//   icon:      SVG path data for a 24x24 viewBox, drawn as a 1.8px stroke
//   component: rendered in the panel while the tab is active (read shared state with useApp() from state.jsx)
//   overlay:   optional component that is always mounted, for map layers that should stay visible on every tab
// Order = order in the nav. On narrow screens the first 4 stay visible and the rest go under "Více".
import Feed, { FeedLive } from "./Feed.jsx";
import Alerts from "./Alerts.jsx";
import Near, { HomePin } from "./Near.jsx";
import Chat from "./Chat.jsx";
import Filters from "./Filters.jsx";
import Sky from "./Sky.jsx";
import Weather from "./Weather.jsx";
import MapLayers from "./MapLayers.jsx";
import Settings from "./Settings.jsx";
import Stats from "./Stats.jsx";
import Watched from "./Watched.jsx";
import Board from "./Board.jsx";
import { PlaybackOverlay } from "./Playback.jsx";

export const TABS = [
  { id: "map", label: "Mapa", icon: "M9 4 3 6.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5zM9 4v13.5M15 6.5V20", component: Feed, overlay: Filters },
  { id: "near", label: "Nad hlavou", icon: "M4 10.5 12 4l8 6.5V20h-5.5v-5.5h-5V20H4z", component: Near, overlay: HomePin },
  { id: "chat", label: "Chat", icon: "M5 5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17h-8l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 5 5z", component: Chat },
  { id: "alerts", label: "Alerty", icon: "M6 9.5a6 6 0 0 1 12 0c0 6 2.5 7.5 2.5 7.5h-17S6 15.5 6 9.5zM10 20.5a2.2 2.2 0 0 0 4 0", component: Alerts, overlay: FeedLive }, // FeedLive: SSE stream, toasts, deep links (Feed.jsx)
  { id: "sky", label: "Obloha", icon: "M12 19a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM12 2v4M12 18v4M2 12h4M18 12h4", component: Sky },
  { id: "stats", label: "Statistiky", icon: "M4 20h16M7 16.5V11M12 16.5V6M17 16.5v-8", component: Stats, overlay: PlaybackOverlay },
  { id: "weather", label: "Počasí a hluk", icon: "M7 15a4 4 0 0 1-.6-7.96A5.5 5.5 0 0 1 17 7.5a3.75 3.75 0 0 1 .5 7.47M4 19c1.5-1.3 3-1.3 4.5 0s3 1.3 4.5 0 3-1.3 4.5 0", component: Weather, overlay: MapLayers }, // MapLayers: radar/airspace overlays + switcher on the map
  { id: "watched", label: "Sledované", icon: "M12 3.5l2.6 5.3 5.8.8-4.2 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z", component: Watched },
  { id: "board", label: "Tabule", icon: "M3.5 5.5h17v13h-17zM3.5 12h17M7 8.5h3M12 8.5h5M7 15.5h3M12 15.5h5", component: Board },
  { id: "settings", label: "Nastavení", icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 13.5l1.6 1.2-2 3.5-1.9-.7a7 7 0 0 1-1.8 1l-.3 2h-4l-.3-2a7 7 0 0 1-1.8-1l-1.9.7-2-3.5 1.6-1.2a7 7 0 0 1 0-3L3 9.3l2-3.5 1.9.7a7 7 0 0 1 1.8-1l.3-2h4l.3 2a7 7 0 0 1 1.8 1l1.9-.7 2 3.5-1.6 1.2a7 7 0 0 1 0 3z", component: Settings },
];
