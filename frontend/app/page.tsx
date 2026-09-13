import { AnalyzerSection } from "@/components/AnalyzerSection";
import { Overview } from "@/components/Overview";
import { ResearchDashboard } from "@/components/research/ResearchDashboard";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6 sm:py-12">
      {/* 1. Hero / Live Analyzer -- password input, Live Estimator Comparison,
          password structure (segmentation strip + match details + PCFG) all
          live inside AnalyzerSection -> ResultPanel. */}
      <Overview />
      <AnalyzerSection />
      {/* 4-13. Why IndicPass? / Representative Cases / Independent Validation /
          OOV & Generalization / Classifier Evaluation / Attack-Budget Analysis /
          Category & OOV Performance / Dataset & Dictionary / Reproducibility /
          Limitations. See ResearchDashboard for the section-by-section order. */}
      <ResearchDashboard />
    </main>
  );
}
