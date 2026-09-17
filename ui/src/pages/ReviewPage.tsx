import PageBrowser from "../components/PageBrowser";

export default function ReviewPage() {
  return (
    <PageBrowser
      bucket="review"
      title="Manual Review"
      description="Pages the split gate could not classify with certainty. Inspect each one and decide what to do."
      emptyTitle="Nothing to review"
      emptyHint="Pages land here only when the split model gives an unclear answer or the page is unreadable."
    />
  );
}
