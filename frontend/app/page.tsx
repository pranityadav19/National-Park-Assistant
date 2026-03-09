"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type Citation = {
  source_type: string;
  source_url: string;
  section?: string | null;
};

type AskResponse = {
  answer: string;
  confidence_note: string;
  citations: Citation[];
};

type Park = {
  park_code: string;
  full_name: string;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const EXAMPLES = [
  "How much does it cost to go to Yellowstone?",
  "Is Yellowstone open all year round?",
  "What is the best season to visit Yosemite?",
  "What should I pack for winter in Yellowstone?"
];

export default function HomePage() {
  const [question, setQuestion] = useState(EXAMPLES[0]);
  const [parkName, setParkName] = useState("Yellowstone");
  const [loading, setLoading] = useState(false);
  const [response, setResponse] = useState<AskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [parks, setParks] = useState<Park[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    const run = async () => {
      if (!parkName.trim()) {
        setParks([]);
        return;
      }
      try {
        const res = await fetch(`${API_BASE}/parks?query=${encodeURIComponent(parkName)}`, {
          signal: controller.signal
        });
        if (!res.ok) {
          return;
        }
        const data = (await res.json()) as Park[];
        setParks(data.slice(0, 8));
      } catch {
        setParks([]);
      }
    };
    run();
    return () => controller.abort();
  }, [parkName]);

  const heroImage = useMemo(() => {
    const query = parkName.trim() || "national park";
    return `https://source.unsplash.com/1600x900/?${encodeURIComponent(query)},landscape`;
  }, [parkName]);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question, park_name: parkName })
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `Request failed with status ${res.status}`);
      }

      const data = (await res.json()) as AskResponse;
      setResponse(data);
    } catch {
      setError(
        "Could not reach the backend API. Confirm docker is running and http://localhost:8000/health returns status ok."
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="mx-auto max-w-6xl px-4 py-8 md:py-12">
      <section className="fade-up relative overflow-hidden rounded-3xl border border-white/60 shadow-2xl">
        <div
          className="absolute inset-0 bg-cover bg-center"
          style={{ backgroundImage: `linear-gradient(120deg, rgba(9,30,22,.72), rgba(11,37,64,.44)), url(${heroImage})` }}
        />
        <div className="relative px-6 py-10 text-white md:px-10 md:py-14">
          <p className="text-xs uppercase tracking-[0.2em] text-white/80">NPS + Wikivoyage Grounded Answers</p>
          <h1 className="mt-3 max-w-3xl text-4xl leading-tight md:text-6xl">National Parks Assistant</h1>
          <p className="mt-4 max-w-2xl text-sm text-white/90 md:text-base">
            Ask about fees, opening windows, and best seasons with source-backed responses from official NPS data and
            curated travel context.
          </p>
        </div>
      </section>

      <section className="fade-up-delay mt-6 grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
        <form onSubmit={onSubmit} className="glass rounded-3xl p-5 md:p-7">
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="text-xs font-semibold uppercase tracking-[0.15em] text-gray-700">Park</label>
              <input
                list="parks-list"
                className="mt-2 w-full rounded-xl border border-gray-300 bg-white px-3 py-2.5 text-sm outline-none transition focus:border-emerald-700"
                value={parkName}
                onChange={(e) => setParkName(e.target.value)}
                placeholder="Yellowstone"
              />
              <datalist id="parks-list">
                {parks.map((p) => (
                  <option key={p.park_code} value={p.full_name} />
                ))}
              </datalist>
            </div>

            <div>
              <label className="text-xs font-semibold uppercase tracking-[0.15em] text-gray-700">Quick Prompts</label>
              <div className="mt-2 flex flex-wrap gap-2">
                {EXAMPLES.slice(0, 3).map((example) => (
                  <button
                    type="button"
                    key={example}
                    onClick={() => setQuestion(example)}
                    className="rounded-full border border-emerald-800/20 bg-emerald-50 px-3 py-1.5 text-xs text-emerald-900 transition hover:bg-emerald-100"
                  >
                    {example.length > 42 ? `${example.slice(0, 42)}...` : example}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <label className="mt-5 block text-xs font-semibold uppercase tracking-[0.15em] text-gray-700">Question</label>
          <textarea
            className="mt-2 w-full rounded-xl border border-gray-300 bg-white px-3 py-3 text-sm outline-none transition focus:border-emerald-700"
            rows={4}
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
          />

          <button
            type="submit"
            className="mt-4 inline-flex rounded-xl bg-[#173b2e] px-5 py-2.5 text-sm font-semibold text-white transition hover:bg-[#122d23] disabled:opacity-50"
            disabled={loading}
          >
            {loading ? "Finding best sources..." : "Ask Assistant"}
          </button>

          {error && <p className="mt-3 rounded-xl bg-rose-50 px-3 py-2 text-sm text-rose-700">{error}</p>}
        </form>

        <aside className="glass rounded-3xl p-5 md:p-7">
          <h2 className="text-2xl text-[#173b2e]">How Answers Are Built</h2>
          <ul className="mt-4 space-y-3 text-sm text-gray-700">
            <li>1. Official NPS API facts are prioritized for fees and operating hours.</li>
            <li>2. NPS park page scraping fills in missing context where possible.</li>
            <li>3. Wikivoyage adds practical season and travel notes as secondary context.</li>
            <li>4. Each response returns citations so users can verify the source.</li>
          </ul>
        </aside>
      </section>

      {response && (
        <section className="fade-up mt-6 glass rounded-3xl p-5 md:p-7">
          <h2 className="text-3xl text-[#173b2e]">Answer</h2>
          <p className="mt-3 whitespace-pre-wrap text-[15px] leading-7 text-gray-800">{response.answer}</p>
          <p className="mt-4 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900">{response.confidence_note}</p>

          <h3 className="mt-5 text-xl text-[#173b2e]">Sources</h3>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            {response.citations.map((c, idx) => (
              <a
                key={`${c.source_url}-${idx}`}
                className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-sm text-slate-700 transition hover:border-emerald-700 hover:text-emerald-900"
                href={c.source_url}
                target="_blank"
                rel="noreferrer"
              >
                <p className="font-semibold uppercase tracking-wide">{c.source_type}</p>
                <p className="mt-1 text-xs text-gray-500">{c.section ?? "section"}</p>
                <p className="mt-1 truncate text-xs text-blue-700">{c.source_url}</p>
              </a>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
