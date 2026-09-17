import { Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import DocumentsPage from "./pages/DocumentsPage";
import OutputPage from "./pages/OutputPage";
import ReviewPage from "./pages/ReviewPage";
import SkippedPage from "./pages/SkippedPage";
import TemplatePage from "./pages/TemplatePage";

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DocumentsPage />} />
        <Route path="extractions" element={<OutputPage />} />
        <Route path="review" element={<ReviewPage />} />
        <Route path="skipped" element={<SkippedPage />} />
        <Route path="template" element={<TemplatePage />} />
      </Route>
    </Routes>
  );
}
