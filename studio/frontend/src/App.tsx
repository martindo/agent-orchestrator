import { Sidebar } from "./components/common/Sidebar";
import { useTeamStore } from "./store/teamStore";
import { OverviewPage } from "./pages/OverviewPage";
import { AgentsPage } from "./pages/AgentsPage";
import { WorkflowPage } from "./pages/WorkflowPage";
import { GovernancePage } from "./pages/GovernancePage";
import { WorkItemsPage } from "./pages/WorkItemsPage";
import { PreviewPage } from "./pages/PreviewPage";
import { DeployPage } from "./pages/DeployPage";
import { SettingsPage } from "./pages/SettingsPage";
import { RecommendPage } from "./pages/RecommendPage";

function CurrentPage() {
  const view = useTeamStore((s) => s.currentView);

  switch (view) {
    case "overview":
      return <OverviewPage />;
    case "agents":
      return <AgentsPage />;
    case "workflow":
      return <WorkflowPage />;
    case "governance":
      return <GovernancePage />;
    case "workitems":
      return <WorkItemsPage />;
    case "preview":
      return <PreviewPage />;
    case "deploy":
      return <DeployPage />;
    case "settings":
      return <SettingsPage />;
    case "recommend":
      return <RecommendPage />;
  }
}

export function App() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-6">
        <CurrentPage />
      </main>
    </div>
  );
}
