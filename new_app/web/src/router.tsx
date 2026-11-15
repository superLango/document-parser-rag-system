import { createBrowserRouter } from "react-router-dom";

import App from "./App";
import DictionaryPage from "./pages/DictionaryPage";
import DocumentsPage from "./pages/DocumentsPage";
import ExtractionPage from "./pages/ExtractionPage";
import IntegrationTaskPage from "./pages/IntegrationTaskPage";
import IssuesPage from "./pages/IssuesPage";
import RecipesPage from "./pages/RecipesPage";

export const router = createBrowserRouter([
  {
    // 一站式解析：独立页面，不进入带侧边栏的工作区壳。
    path: "/integration/task/:taskId",
    element: <IntegrationTaskPage />
  },
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <DocumentsPage /> },
      { path: "documents/:documentId", element: <ExtractionPage /> },
      { path: "issues", element: <IssuesPage /> },
      { path: "dictionary", element: <DictionaryPage /> },
      { path: "recipes", element: <RecipesPage /> }
    ]
  }
]);
