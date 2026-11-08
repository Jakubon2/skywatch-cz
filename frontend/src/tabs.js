// Tab registry. Adding a feature = a component file + one line here.
//   id:        stable key (also the panel CSS modifier: .panel--<id>)
//   label:     Czech text in the nav
//   icon:      SVG path data for a 24x24 viewBox, drawn as a 1.8px stroke
//   component: rendered in the panel while the tab is active (read shared state with useApp() from state.jsx)
//   overlay:   optional component that is always mounted, for map layers that should stay visible on every tab
// Order = order in the nav. On narrow screens the first 4 stay visible and the rest go under "Více".
import Feed from "./Feed.jsx";
import Near, { HomePin } from "./Near.jsx";
import Chat from "./Chat.jsx";

export const TABS = [
  { id: "map", label: "Mapa", icon: "M9 4 3 6.5v13.5l6-2.5 6 2.5 6-2.5V4l-6 2.5zM9 4v13.5M15 6.5V20", component: Feed },
  { id: "near", label: "Nad hlavou", icon: "M4 10.5 12 4l8 6.5V20h-5.5v-5.5h-5V20H4z", component: Near, overlay: HomePin },
  { id: "chat", label: "Chat", icon: "M5 5h14a1.5 1.5 0 0 1 1.5 1.5v9A1.5 1.5 0 0 1 19 17h-8l-4.5 3.5V17H5a1.5 1.5 0 0 1-1.5-1.5v-9A1.5 1.5 0 0 1 5 5z", component: Chat },
];
