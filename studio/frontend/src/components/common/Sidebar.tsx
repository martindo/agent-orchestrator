import { useTeamStore } from "../../store/teamStore";

const NAV_ITEMS = [
  { view: "overview", label: "Overview", iconSrc: "/assets/icons/overview.png" },
  { view: "recommend", label: "AI Recommend", iconSrc: "/assets/icons/recommend.png" },
  { view: "agents", label: "Agents", iconSrc: "/assets/icons/agents.png" },
  { view: "workflow", label: "Workflow", iconSrc: "/assets/icons/workflow.png" },
  { view: "governance", label: "Governance", iconSrc: "/assets/icons/governance.png" },
  { view: "workitems", label: "Work Items", iconSrc: "/assets/icons/workitems.png" },
  { view: "preview", label: "Preview", iconSrc: "/assets/icons/preview.png" },
  { view: "deploy", label: "Deploy", iconSrc: "/assets/icons/deploy.png" },
  { view: "settings", label: "Settings", iconSrc: "/assets/icons/settings.png" },
] as const;

export function Sidebar() {
  const currentView = useTeamStore((s) => s.currentView);
  const setView = useTeamStore((s) => s.setView);
  const team = useTeamStore((s) => s.team);

  return (
    <aside className="w-60 shrink-0 bg-gray-900 text-gray-100 flex flex-col h-screen">
      <div className="px-4 py-5 border-b border-gray-700">
        <img src="/assets/logo.png" alt="AO Studio" className="w-full px-2" />
        {team ? (
          <p className="text-sm text-gray-400 mt-2 truncate">{team.name}</p>
        ) : (
          <p className="text-sm text-gray-500 mt-2">No team loaded</p>
        )}
      </div>

      <nav className="flex-1 py-4 space-y-1 px-2">
        {NAV_ITEMS.map((item) => {
          const active = currentView === item.view;
          return (
            <button
              key={item.view}
              onClick={() => setView(item.view)}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                active
                  ? "bg-indigo-600 text-white"
                  : "text-gray-300 hover:bg-gray-800 hover:text-white"
              }`}
            >
              <img src={item.iconSrc} alt={item.label} className="w-5 h-5" />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      <div className="px-4 py-3 border-t border-gray-700 text-xs text-gray-500">
        Agent Orchestrator Studio v0.1
      </div>
    </aside>
  );
}
