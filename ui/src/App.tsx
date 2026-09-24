import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import DocumentsPage from "./pages/DocumentsPage";
import PipelinePage from "./pages/PipelinePage";
import OutputPage from "./pages/OutputPage";
import ReviewPage from "./pages/ReviewPage";
import SkippedPage from "./pages/SkippedPage";
import TemplatePage from "./pages/TemplatePage";
import CostsPage from "./pages/CostsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DocumentsPage />} />
        <Route path="pipeline" element={<PipelinePage />} />
        <Route path="extractions" element={<OutputPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="skipped" element={<SkippedPage />} />
        <Route path="template" element={<TemplatePage />} />
        <Route path="costs" element={<CostsPage />} />
      </Route>
    </Routes>
  );
}
