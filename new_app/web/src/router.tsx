import { createBrowserRouter } from "react-router-dom";

import App from "./App";
import DictionaryPage from "./pages/DictionaryPage";
import DocumentsPage from "./pages/DocumentsPage";
import ExtractionPage from "./pages/ExtractionPage";
import RecipesPage from "./pages/RecipesPage";
import RunsPage from "./pages/RunsPage";
import ViewerPage from "./pages/ViewerPage";

export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
    children: [
      { index: true, element: <DocumentsPage /> },
      { path: "documents/:documentId", element: <ExtractionPage /> },
      { path: "documents/:documentId/viewer", element: <ViewerPage /> },
      { path: "runs", element: <RunsPage /> },
      { path: "dictionary", element: <DictionaryPage /> },
      { path: "recipes", element: <RecipesPage /> }
    ]
  }
]);
