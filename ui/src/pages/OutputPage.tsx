import PageBrowser from "../components/PageBrowser";

export default function OutputPage() {
  return (
    <PageBrowser
      bucket="output"
      title="Extractions"
      description="Pages that went through the full pipeline: routed to a model and parsed into fields."
      emptyTitle="No extractions yet"
      emptyHint="Add PDFs on the Documents page and run the pipeline to see results here."
    />
  );
}
