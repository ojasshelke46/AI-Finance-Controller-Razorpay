"use client";

import { useState } from "react";

import { Panel, PanelHeader, Pill, Skeleton, StatusDot } from "@/components/primitives";
import { askQuestion, type QnaResponse } from "@/lib/api";

const SUGGESTIONS = [
  "Which matching tier contributed the most transactions, and how many?",
  "How much value is still sitting open in the variance queue?",
  "What was the precision of this run, and how many false positives is that?",
];

export function QnaConsole({ batchId }: { batchId: string }) {
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
      setError(caught instanceof Error ? caught.message : "The question could not be answered");
    } finally {
      setLoading(false);
    }
  }

  const guardFired = answer?.attempts.some((a) => (a.ungrounded_figures?.length ?? 0) > 0);

  return (
    <Panel>
      <PanelHeader
        title="Ask about this run"
        description="Answers are built only from the figures listed alongside. Every number in the reply is checked against those figures before it is shown."
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
              Generating, then verifying every figure against the run data…
            </p>
          </div>
        ) : error ? (
          <div className="border border-critical/30 bg-critical-bg px-3 py-2.5">
            <p className="text-[12.5px] text-critical">{error}</p>
          </div>
        ) : answer ? (
          <div className="space-y-3" aria-live="polite">
            <p className="text-[12px] text-muted-foreground">{answer.question}</p>

            <div
              className={
                answer.verified
                  ? "border-l-2 border-ok pl-3"
                  : "border-l-2 border-critical bg-critical-bg/40 py-2 pl-3"
              }
            >
              <p className="text-[13px] leading-relaxed">{answer.answer}</p>
            </div>

            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
              <Pill severity={answer.verified ? "ok" : "critical"}>
                <StatusDot severity={answer.verified ? "ok" : "critical"} />
                {answer.verified ? "Every figure traced" : "Withheld — untraceable figure"}
              </Pill>
              {guardFired ? (
                <Pill severity="warn">Guard fired · regenerated</Pill>
              ) : null}
              <span className="num text-[11px] text-muted-foreground">
                {answer.attempts.length} attempt{answer.attempts.length === 1 ? "" : "s"} ·{" "}
                {answer.context_chars} chars of context
              </span>
            </div>

            <details className="text-[11.5px]">
              <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
                Verification detail
              </summary>
              <ul className="mt-2 space-y-1.5">
                {answer.attempts.map((attempt) => (
                  <li key={attempt.attempt} className="num flex flex-wrap gap-x-3">
                    <span>attempt {attempt.attempt}</span>
                    {attempt.error ? (
                      <span className="text-critical">{attempt.error}</span>
                    ) : (
                      <>
                        <span
                          className={
                            (attempt.ungrounded_figures?.length ?? 0) > 0
                              ? "text-critical"
                              : "text-ok"
                          }
                        >
                          {(attempt.ungrounded_figures?.length ?? 0) > 0
                            ? `untraceable: ${attempt.ungrounded_figures!.join(", ")}`
                            : "all figures traced"}
                        </span>
                        <span className="text-muted-foreground">
                          {attempt.latency_ms?.toFixed(0)}ms · {attempt.total_tokens ?? "—"} tokens
                        </span>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </details>
          </div>
        ) : (
          <p className="text-[12px] text-muted-foreground">
            Ask a question about this run. If the data cannot answer it, the system says so
            rather than estimating.
          </p>
        )}
      </div>
    </Panel>
  );
}
