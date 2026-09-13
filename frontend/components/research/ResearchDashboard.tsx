import { ResearchNotes } from "../ResearchNotes";
import { CaseStudies } from "./CaseStudies";
import { ValidationSection } from "./ValidationSection";
import { OovGeneralization } from "./OovGeneralization";
import { ClassifierEvaluation } from "./ClassifierEvaluation";
import { AttackBudgetSection } from "./AttackBudgetSection";
import { CategoryBreakdown } from "./CategoryBreakdown";
import { DictionaryCoverage } from "./DictionaryCoverage";
import { Reproducibility } from "./Reproducibility";
import { Limitations } from "./Limitations";

/**
 * Everything below the live analyzer: sections 4-13 of the dashboard order
 * (Why IndicPass? through Limitations). Kept as one assembly point so
 * `app/page.tsx` reads as the ordering document for the whole page.
 */
export function ResearchDashboard() {
  return (
    <div className="space-y-6">
      <ResearchNotes />
      <CaseStudies />
      <ValidationSection />
      <OovGeneralization />
      <ClassifierEvaluation />
      <AttackBudgetSection />
      <CategoryBreakdown />
      <DictionaryCoverage />
      <Reproducibility />
      <Limitations />
    </div>
  );
}
