"use strict";

(function () {
  const form = document.getElementById("lookup-form");
  const statusBox = document.getElementById("status");
  const results = document.getElementById("results");
  const submitBtn = document.getElementById("submit-btn");
  const languageSelect = document.getElementById("language");

  const API = (window.API_PREFIX || "/api/v1") + "/cases/lookup";

  const KIND_LABELS = {
    bn: { cr: "সি.আর.", gr: "জি.আর.", civil: "দেওয়ানি", criminal: "ফৌজদারি", unknown: "অনির্ধারিত" },
    en: { cr: "Criminal Revision", gr: "Police case (GR)", civil: "Civil", criminal: "Criminal", unknown: "Unknown" },
  };

  const ROLE_LABELS = {
    bn: { plaintiff: "বাদী", defendant: "বিবাদী", accused: "আসামি", petitioner: "আবেদনকারী", respondent: "বিবাদী", complainant: "বাদী", unknown: "পক্ষ" },
    en: { plaintiff: "Plaintiff", defendant: "Defendant", accused: "Accused", petitioner: "Petitioner", respondent: "Respondent", complainant: "Complainant", unknown: "Party" },
  };

  const T = {
    bn: {
      searching: "খোঁজা হচ্ছে…",
      notFound: "এই নম্বরে কোনো মামলা পাওয়া যায়নি।",
      error: "সংযোগে সমস্যা হয়েছে। আবার চেষ্টা করুন।",
      summary: "সারসংক্ষেপ",
      explanation: "সহজ ব্যাখ্যা",
      steps: "প্রয়োজনীয় পদক্ষেপ",
      caseNo: "মামলা নম্বর",
      type: "ধরন",
      court: "আদালত",
      status: "অবস্থা",
      next: "পরবর্তী শুনানি",
      parties: "পক্ষগণ",
      subject: "বিষয়",
      order: "সর্বশেষ আদেশ",
      privacy: "ব্যক্তিগত তথ্য মাস্ক করা হয়েছে",
      cached: "সংরক্ষিত ফলাফল",
      fallback: "সর্বশেষ সংরক্ষিত ফলাফল",
    },
    en: {
      searching: "Searching…",
      notFound: "No case found for this number.",
      error: "A connection problem occurred. Please try again.",
      summary: "Summary",
      explanation: "Plain-language explanation",
      steps: "Next steps",
      caseNo: "Case number",
      type: "Type",
      court: "Court",
      status: "Status",
      next: "Next hearing",
      parties: "Parties",
      subject: "Subject",
      order: "Latest order",
      privacy: "Personal data masked",
      cached: "Cached result",
      fallback: "Last saved result",
    },
  };

  const esc = (value) =>
    String(value == null ? "" : value).replace(/[&<>"']/g, (ch) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch])
    );

  function showStatus(kind, message) {
    const styles = {
      error: "bg-red-50 text-red-700 border border-red-200",
      info: "bg-slate-100 text-slate-700 border border-slate-200",
      ok: "bg-teal-50 text-teal-700 border border-teal-200",
    };
    statusBox.className = "mt-4 rounded-lg px-4 py-3 text-sm " + (styles[kind] || styles.info);
    statusBox.textContent = message;
    statusBox.classList.remove("hidden");
  }

  function row(label, value) {
    if (value == null || value === "") return "";
    return `<div class="flex gap-3 py-1.5"><dt class="w-32 shrink-0 text-slate-500">${esc(label)}</dt><dd class="text-slate-800">${esc(value)}</dd></div>`;
  }

  function render(data, lang) {
    const t = T[lang];
    results.innerHTML = "";

    if (!data.found || !data.summary) {
      results.innerHTML = `<div class="rounded-xl border border-amber-200 bg-amber-50 p-5 text-amber-800">${esc(
        data.message || t.notFound
      )}</div>`;
      return;
    }

    const s = data.summary;
    const kind = KIND_LABELS[lang][s.kind] || s.kind;
    const parties = (s.parties || [])
      .map((p) => `${ROLE_LABELS[lang][p.role] || ""}: ${p.name}`)
      .join(" · ");

    const badge =
      data.source === "cache"
        ? `<span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600">${esc(t.cached)}</span>`
        : data.source === "fallback"
        ? `<span class="rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700">${esc(t.fallback)}</span>`
        : "";

    const privacy =
      data.privacy && data.privacy.applied
        ? `<span class="rounded-full bg-teal-100 px-2 py-0.5 text-xs text-teal-700">${esc(t.privacy)} (${data.privacy.total})</span>`
        : "";

    const steps = (data.next_steps || [])
      .map((step) => `<li class="flex gap-2"><span class="text-brand">•</span><span>${esc(step)}</span></li>`)
      .join("");

    results.innerHTML = `
      <div class="rounded-xl bg-white p-5 shadow-sm sm:p-6">
        <div class="flex flex-wrap items-center gap-2">
          <h3 class="text-lg font-bold text-slate-900">${esc(s.normalized_number || s.case_number)}</h3>
          ${badge}${privacy}
        </div>
        <dl class="mt-3 text-sm">
          ${row(t.type, kind)}
          ${row(t.court, s.court)}
          ${row(t.status, s.status)}
          ${row(t.next, s.next_hearing_date)}
          ${row(t.subject, s.subject)}
          ${row(t.parties, parties)}
          ${row(t.order, s.last_order_summary)}
        </dl>
      </div>
      ${
        data.explanation
          ? `<div class="rounded-xl bg-white p-5 shadow-sm sm:p-6">
              <h4 class="mb-2 text-sm font-semibold text-slate-900">${esc(t.explanation)}</h4>
              <p class="whitespace-pre-line text-sm leading-relaxed text-slate-700">${esc(data.explanation)}</p>
            </div>`
          : ""
      }
      ${
        steps
          ? `<div class="rounded-xl bg-teal-50 p-5 shadow-sm sm:p-6">
              <h4 class="mb-2 text-sm font-semibold text-teal-900">${esc(t.steps)}</h4>
              <ul class="space-y-1.5 text-sm text-teal-900">${steps}</ul>
            </div>`
          : ""
      }
    `;
  }

  async function lookup(payload, lang) {
    showStatus("info", T[lang].searching);
    submitBtn.disabled = true;
    try {
      const response = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const data = await response.json();
      statusBox.classList.add("hidden");
      render(data, lang);
    } catch (err) {
      results.innerHTML = "";
      showStatus("error", T[lang].error);
      console.error(err);
    } finally {
      submitBtn.disabled = false;
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const lang = languageSelect.value === "en" ? "en" : "bn";
    const courtId = document.getElementById("court_id").value.trim();
    const payload = {
      case_number: document.getElementById("case_number").value.trim(),
      court: document.getElementById("court").value.trim() || null,
      court_id: courtId ? Number(courtId) : null,
      language: lang,
      force_refresh: document.getElementById("force_refresh").checked,
    };
    if (!payload.case_number) return;
    lookup(payload, lang);
  });
})();
