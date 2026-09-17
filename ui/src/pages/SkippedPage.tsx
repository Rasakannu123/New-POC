import PageBrowser from "../components/PageBrowser";

export default function SkippedPage() {
  return (
    <PageBrowser
      bucket="skip"
      title="Skipped Pages"
      description="Pages the split gate marked as not needed because they match a no_need_page field from the template."
      emptyTitle="No skipped pages"
      emptyHint="When the split model answers yes, the page is stored here instead of being extracted."
    />
  );
}
