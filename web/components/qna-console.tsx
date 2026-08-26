"use client";

import { useMemo, useState } from "react";

import { Panel, PanelHeader, Pill, Skeleton, StatusDot } from "@/components/primitives";
import { askQuestion, type QnaResponse } from "@/lib/api";
import { figureKey, markFigures, TRACED_MARK } from "@/lib/figures";
import { formatCount } from "@/lib/money";
import { cn } from "@/lib/utils";

const SUGGESTIONS = [
  "Which matching tier contributed the most transactions, and how many?",
  "How much value is still sitting open in the variance queue?",
  "What was the precision of this run, and how many false positives is that?",
];

export type Fact = { label: string; value: string };

export function QnaConsole({ batchId, facts }: { batchId: string; facts: Fact[] }) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<QnaResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(text: string) {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setLoading(true);
    setError(null);
    setAnswer(null);
    try {
      setAnswer(await askQuestion(batchId, trimmed));
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The question could not be answered. Try again in a moment.",
      );
    } finally {
      setLoading(false);
    }
  }

  /** Which of the batch's own figures the answer actually quoted. This
   *  is the traceability claim made concrete: not "trust this", but
   *  "here is the figure, and here is the fact it came from". */
  const used = useMemo(() => {
    if (!answer?.verified) return [];
    return facts.filter(
      (fact) =>
        figureKey(fact.value).length > 0 &&
        figureKey(answer.answer).includes(figureKey(fact.value)),
    );
  }, [answer, facts]);

  const untraceable = answer?.attempts.flatMap((a) => a.ungrounded_figures ?? []) ?? [];
  const retried = (answer?.attempts.length ?? 0) > 1;

  return (
    <Panel>
      <PanelHeader
        title="Ask about this run"
        description="Answers are built only from the figures listed alongside. Every number in a reply is checked against those figures before it is shown, and an answer that cites anything else is withheld."
      />

      <form
        onSubmit={(event) => {
          event.preventDefault();
          ask(question);
        }}
        className="border-b border-border px-4 py-3"
      >
        <label htmlFor="qna-question" className="label">
          Question
        </label>
        <div className="mt-1.5 flex gap-2">
          <input
            id="qna-question"
            name="question"
            type="text"
            autoComplete="off"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="What is still unreconciled in this batch?"
            className="min-h-[34px] flex-1 rounded-sm border border-border bg-surface px-2.5 py-1.5 text-[12.5px] placeholder:text-muted-foreground"
          />
          <button
            type="submit"
            disabled={loading || question.trim().length === 0}
            className="min-h-[34px] rounded-sm border border-border-strong px-3 text-[12.5px] font-medium whitespace-nowrap transition-colors hover:bg-muted disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? "Checking…" : "Ask"}
          </button>
        </div>

        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              onClick={() => {
                setQuestion(suggestion);
                ask(suggestion);
              }}
              disabled={loading}
              className="rounded-sm border border-border px-2 py-[3px] text-left text-[11.5px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
            >
              {suggestion}
            </button>
          ))}
        </div>
      </form>

      <div className="px-4 py-4">
        {loading ? (
          <div className="space-y-2" aria-live="polite">
            <Skeleton className="h-3 w-2/3" />
            <Skeleton className="h-3 w-full" />
            <Skeleton className="h-3 w-4/5" />
            <p className="pt-1 text-[11.5px] text-muted-foreground">
              Writing an answer, then checking every figure in it against this batch&apos;s
              records.
            </p>
          </div>
        ) : error ? (
          <div className="border border-critical/30 bg-critical-bg px-3 py-2.5">
            <p className="text-[12.5px] text-critical">{error}</p>
            <p className="mt-1 text-[11.5px] text-muted-foreground">
              Nothing was answered. Ask again, or check that the reconciliation service is
              running.
            </p>
          </div>
        ) : answer ? (
          <div className="space-y-3" aria-live="polite">
            <p className="text-[12px] text-muted-foreground">{answer.question}</p>

            {/* The verdict comes before the words it applies to. */}
            <div className="flex flex-wrap items-center gap-2">
              <Pill severity={answer.verified ? "ok" : "critical"}>
                <StatusDot severity={answer.verified ? "ok" : "critical"} />
                {answer.verified ? "Every figure traced" : "Withheld — untraceable figure"}
              </Pill>
              {retried ? (
                <span className="text-[11px] text-muted-foreground">
                  first draft cited a figure that could not be traced; regenerated once
                </span>
              ) : null}
            </div>

            <div
              className={cn(
                "border-l pl-3",
                answer.verified ? "border-ok" : "border-critical bg-critical-bg/40 py-2",
              )}
            >
              <p className="text-[13px] leading-relaxed">
                {answer.verified
                  ? markFigures(
                      answer.answer,
                      used.map((fact) => fact.value),
                    )
                  : answer.answer}
              </p>
            </div>

            {answer.verified ? (
              used.length > 0 ? (
                <section>
                  <h3 className="label mb-1.5">Figures this answer was built from</h3>
                  <dl className="divide-y divide-border border-y border-border">
                    {used.map((fact) => (
                      <div
                        key={fact.label}
                        className="flex items-baseline justify-between gap-3 py-1.5"
                      >
                        <dt className="text-[12px] text-muted-foreground">{fact.label}</dt>
                        <dd className={cn("num text-[12px]", TRACED_MARK)}>{fact.value}</dd>
                      </div>
                    ))}
                  </dl>
                  <p className="mt-1.5 text-[11px] text-muted-foreground">
                    Each figure above appears in the answer and was read from this batch,
                    not produced by the model.
                  </p>
                </section>
              ) : (
                <p className="text-[11.5px] text-muted-foreground">
                  This answer quotes no figure, so there is nothing to trace. It passed the
                  same check regardless.
                </p>
              )
            ) : untraceable.length > 0 ? (
              <section>
                <h3 className="label mb-1.5">
                  Figures that could not be traced ({formatCount(untraceable.length)})
                </h3>
                <ul className="flex flex-wrap gap-1.5">
                  {untraceable.map((figure, index) => (
                    <li key={`${figure}-${index}`}>
                      <Pill severity="critical">
                        <span className="num normal-case">{figure}</span>
                      </Pill>
                    </li>
                  ))}
                </ul>
                <p className="mt-1.5 text-[11px] text-muted-foreground">
                  These appeared in the draft but in none of this batch&apos;s records, so
                  the draft was discarded rather than shown.
                </p>
              </section>
            ) : null}
          </div>
        ) : (
          <p className="text-[12px] text-muted-foreground">
            Ask a question about this run. If the figures alongside cannot answer it, the
            system says so rather than estimating.
          </p>
        )}
      </div>
    </Panel>
  );
}
