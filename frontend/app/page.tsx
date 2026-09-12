import { AnalyzerSection } from "@/components/AnalyzerSection";
import { Overview } from "@/components/Overview";
import { ResearchNotes } from "@/components/ResearchNotes";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6 sm:py-12">
      <Overview />
      <AnalyzerSection />
      <ResearchNotes />
    </main>
  );
}
