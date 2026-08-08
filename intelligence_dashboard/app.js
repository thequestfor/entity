const elements = {
  connection: document.querySelector("#connection"),
  documentCount: document.querySelector("#document-count"),
  situationCount: document.querySelector("#situation-count"),
  claimCount: document.querySelector("#claim-count"),
  contestedCount: document.querySelector("#contested-count"),
  sourceCount: document.querySelector("#source-count"),
  issueCount: document.querySelector("#issue-count"),
  lastRetrieval: document.querySelector("#last-retrieval"),
  categoryFilter: document.querySelector("#category-filter"),
  briefingHeadline: document.querySelector("#briefing-headline"),
  briefingPeriod: document.querySelector("#briefing-period"),
  worldMap: document.querySelector("#world-map"),
  mapStatus: document.querySelector("#map-status"),
  mapPriorityFilter: document.querySelector("#map-priority-filter"),
  situationList: document.querySelector("#situation-list"),
  situationDetail: document.querySelector("#situation-detail"),
  documentFeed: document.querySelector("#document-feed"),
  sourceList: document.querySelector("#source-list"),
  reputationList: document.querySelector("#reputation-list"),
  forecastList: document.querySelector("#forecast-list"),
  clusterReviewCount: document.querySelector("#cluster-review-count"),
  dependentReportCount: document.querySelector("#dependent-report-count"),
  typedClaimCount: document.querySelector("#typed-claim-count"),
  integrityReviewCount: document.querySelector("#integrity-review-count"),
  epistemicBackfillStatus: document.querySelector("#epistemic-backfill-status"),
  corroboratedClaimCount: document.querySelector("#corroborated-claim-count"),
  truthDisputeCount: document.querySelector("#truth-dispute-count"),
  verificationTaskCount: document.querySelector("#verification-task-count"),
  intelligenceGapCount: document.querySelector("#intelligence-gap-count"),
  reasoningJobCount: document.querySelector("#reasoning-job-count"),
  documentTemplate: document.querySelector("#document-template"),
  situationTemplate: document.querySelector("#situation-template")
};

let selectedCategory = "";
let selectedSituationId = "";
let mapPriority = "priority";

async function request(path) {
  const response = await fetch(path, {
    headers: { Accept: "application/json" },
    cache: "no-store"
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function formatTime(value) {
  if (!value) return "Never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(date);
}

function safeExternalUrl(value) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch (error) {
    return "";
  }
}

function setConnection(online) {
  elements.connection.dataset.online = String(online);
  elements.connection.querySelector("span").textContent = online
    ? "LOCAL SERVICE ONLINE"
    : "RECONNECTING";
}

function renderOverview(overview) {
  elements.documentCount.textContent = overview.documents ?? 0;
  elements.situationCount.textContent = overview.situations ?? 0;
  elements.claimCount.textContent = overview.claims ?? 0;
  elements.contestedCount.textContent = overview.contested_claims ?? 0;
  elements.sourceCount.textContent = overview.sources ?? 0;
  elements.issueCount.textContent = overview.unhealthy ?? 0;
  elements.clusterReviewCount.textContent = overview.cluster_reviews ?? 0;
  elements.dependentReportCount.textContent = overview.dependent_reports ?? 0;
  elements.typedClaimCount.textContent = overview.epistemically_typed_claims ?? 0;
  elements.integrityReviewCount.textContent = overview.integrity_reviews ?? 0;
  elements.corroboratedClaimCount.textContent = overview.corroborated_claims ?? 0;
  elements.truthDisputeCount.textContent = overview.disputed_truth_claims ?? 0;
  elements.verificationTaskCount.textContent = overview.verification_tasks ?? 0;
  elements.intelligenceGapCount.textContent = overview.intelligence_gaps ?? 0;
  elements.reasoningJobCount.textContent = overview.pending_reasoning_jobs ?? 0;
  const processed = overview.epistemic_backfill_processed ?? 0;
  elements.epistemicBackfillStatus.textContent = overview.epistemic_backfill_complete
    ? `Historical epistemic backfill complete · ${processed} records reviewed`
    : `Historical epistemic backfill in progress · ${processed} records reviewed`;
  elements.lastRetrieval.textContent = formatTime(overview.latest_retrieved_at);

  const current = elements.categoryFilter.value;
  const existing = new Set(
    [...elements.categoryFilter.options].map((option) => option.value)
  );
  for (const category of overview.categories ?? []) {
    if (existing.has(category.category)) continue;
    const option = document.createElement("option");
    option.value = category.category;
    option.textContent = `${category.category} (${category.count})`;
    elements.categoryFilter.append(option);
  }
  elements.categoryFilter.value = current;
}

function renderBriefing(briefing) {
  elements.briefingHeadline.textContent =
    briefing.content?.headline || "No briefing is available yet.";
  elements.briefingPeriod.textContent = briefing.period_end
    ? `${formatTime(briefing.period_start)} — ${formatTime(briefing.period_end)}`
    : "The first briefing will appear after evidence is analyzed.";
}

function renderSituations(situations) {
  elements.situationList.replaceChildren();
  if (!situations.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No situations have been formed for this view yet.";
    elements.situationList.append(empty);
    return;
  }
  for (const situation of situations) {
    const fragment = elements.situationTemplate.content.cloneNode(true);
    const button = fragment.querySelector("button");
    button.dataset.status = situation.status;
    button.dataset.situationId = situation.id;
    button.dataset.selected = String(situation.id === selectedSituationId);
    fragment.querySelector(".category").textContent = situation.category;
    fragment.querySelector(".status").textContent = situation.status;
    fragment.querySelector("strong").textContent = situation.title;
    fragment.querySelector(".situation-stats").textContent =
      `${Math.round(situation.confidence * 100)}% confidence · ` +
      `${situation.evidence_count} evidence · ${situation.source_count} sources`;
    fragment.querySelector(".confidence-track i").style.width =
      `${Math.round(situation.confidence * 100)}%`;
    button.addEventListener("click", () => selectSituation(situation.id));
    elements.situationList.append(fragment);
  }
}

function renderMap(situations) {
  elements.worldMap.replaceChildren();
  const located = situations.filter((situation) =>
    Number.isFinite(situation.latitude) && Number.isFinite(situation.longitude)
  );
  const displayed = selectMapSituations(located);
  elements.mapStatus.textContent = displayed.length
    ? `${displayed.length} shown · ${located.length} located available`
    : "No located situations in this view";
  if (!displayed.length) {
    const empty = document.createElement("p");
    empty.className = "map-empty";
    empty.textContent = "No located situations are available in this view.";
    elements.worldMap.append(empty);
    return;
  }
  for (const situation of displayed) {
    const point = document.createElement("button");
    point.type = "button";
    point.className = "map-point";
    point.dataset.status = situation.status;
    point.dataset.situationId = situation.id;
    point.dataset.selected = String(situation.id === selectedSituationId);
    point.style.left = `${((situation.longitude + 180) / 360) * 100}%`;
    point.style.top = `${((90 - situation.latitude) / 180) * 100}%`;
    point.title = `${situation.title} · ${Math.round(situation.confidence * 100)}%`;
    point.setAttribute("aria-label", point.title);
    point.addEventListener("click", () => selectSituation(situation.id));
    elements.worldMap.append(point);
  }
}

function selectMapSituations(situations) {
  if (mapPriority === "all") return situations;
  const active = situations.filter((situation) => situation.status === "active");
  if (mapPriority === "active") return active.slice(0, 75);
  return active
    .map((situation) => ({ situation, score: mapPriorityScore(situation) }))
    .sort((left, right) => right.score - left.score)
    .slice(0, 30)
    .map((item) => item.situation);
}

function mapPriorityScore(situation) {
  const timestamp = new Date(situation.last_seen_at || situation.updated_at);
  const ageHours = Number.isNaN(timestamp.getTime())
    ? 168
    : Math.max(0, (Date.now() - timestamp.getTime()) / 3_600_000);
  const freshness = Math.max(0, 3 - ageHours / 24);
  return (
    (situation.status === "contested" ? 5 : 0) +
    Number(situation.confidence || 0) * 2 +
    Math.min(3, Number(situation.source_count || 0)) +
    Math.min(1, Number(situation.evidence_count || 0) / 10) +
    freshness
  );
}

function selectSituation(id) {
  selectedSituationId = id;
  for (const item of document.querySelectorAll("[data-situation-id]")) {
    item.dataset.selected = String(item.dataset.situationId === id);
  }
  loadSituation(id);
  document.querySelector(`[data-situation-id="${CSS.escape(id)}"]`)?.scrollIntoView({
    behavior: "smooth", block: "nearest"
  });
}

async function loadSituation(id) {
  elements.situationDetail.textContent = "Loading evidence chain…";
  try {
    const detail = await request(`/api/intelligence/situations/${encodeURIComponent(id)}`);
    renderSituationDetail(detail);
  } catch (error) {
    elements.situationDetail.textContent = "Could not load this situation.";
  }
}

function renderSituationDetail(detail) {
  elements.situationDetail.replaceChildren();
  const heading = document.createElement("h3");
  heading.textContent = "Claims and confidence history";
  elements.situationDetail.append(heading);
  const situation = detail.situation ?? {};
  if (Number.isFinite(situation.latitude) && Number.isFinite(situation.longitude)) {
    const map = document.createElement("div");
    map.className = "situation-map";
    const marker = document.createElement("i");
    marker.style.left = `${((situation.longitude + 180) / 360) * 100}%`;
    marker.style.top = `${((90 - situation.latitude) / 180) * 100}%`;
    marker.title = `${situation.latitude.toFixed(3)}, ${situation.longitude.toFixed(3)}`;
    const label = document.createElement("span");
    label.textContent = `Reported location: ${situation.latitude.toFixed(3)}, ${situation.longitude.toFixed(3)}`;
    map.append(marker, label);
    elements.situationDetail.append(map);
  }
  const claims = document.createElement("div");
  claims.className = "claims";
  for (const claim of detail.claims ?? []) {
    const row = document.createElement("div");
    row.className = "claim";
    row.dataset.status = claim.status;
    const assertion = document.createElement("span");
    assertion.textContent = `${claim.predicate}: ${claim.object}`;
    const confidence = document.createElement("small");
    const sourceNames = [
      ...new Set((claim.evidence ?? []).map((item) => item.source_name))
    ];
    confidence.textContent =
      `${claim.status} / ${claim.truth_status || "unverified"} · ` +
      `${Math.round(Number(claim.resolution_confidence || claim.confidence) * 100)}% · ` +
      `${sourceNames.join(", ") || `${claim.source_count} source(s)`}`;
    row.append(assertion, confidence);
    const evidenceLinks = document.createElement("span");
    evidenceLinks.className = "claim-evidence";
    for (const evidence of claim.evidence ?? []) {
      const safeUrl = safeExternalUrl(evidence.url);
      if (!safeUrl) continue;
      const link = document.createElement("a");
      link.href = safeUrl;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = `${evidence.source_name} v${evidence.document_version}`;
      evidenceLinks.append(link);
    }
    if (evidenceLinks.childElementCount) row.append(evidenceLinks);
    claims.append(row);
  }
  elements.situationDetail.append(claims);
  const hypotheses = document.createElement("div");
  hypotheses.className = "hypotheses";
  for (const hypothesis of detail.hypotheses ?? []) {
    const card = document.createElement("div");
    card.className = "hypothesis";
    const title = document.createElement("strong");
    title.textContent = `${Math.round(Number(hypothesis.probability || 0) * 100)}% · ${hypothesis.title}`;
    const description = document.createElement("small");
    description.textContent = hypothesis.description;
    const falsifier = document.createElement("small");
    falsifier.textContent = `Would change Entity's mind: ${(hypothesis.falsifiers ?? []).join(" ")}`;
    card.append(title, description, falsifier);
    hypotheses.append(card);
  }
  if (hypotheses.childElementCount) {
    const heading = document.createElement("h3");
    heading.textContent = "Competing hypotheses";
    elements.situationDetail.append(heading, hypotheses);
  }
  const history = document.createElement("p");
  history.className = "history-heading";
  history.textContent = `${detail.documents?.length ?? 0} linked evidence record(s) · confidence history`;
  elements.situationDetail.append(history);
  const timeline = document.createElement("div");
  timeline.className = "timeline";
  for (const snapshot of detail.timeline ?? []) {
    const entry = document.createElement("div");
    entry.className = "timeline-entry";
    entry.textContent =
      `v${snapshot.version} · ${Math.round(snapshot.confidence * 100)}% · ` +
      `${snapshot.status} · ${formatTime(snapshot.created_at)}`;
    timeline.append(entry);
  }
  elements.situationDetail.append(timeline);
}

function renderDocuments(documents) {
  elements.documentFeed.replaceChildren();

  if (!documents.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No evidence has been collected for this view yet.";
    elements.documentFeed.append(empty);
    return;
  }

  for (const documentRecord of documents) {
    const fragment = elements.documentTemplate.content.cloneNode(true);
    fragment.querySelector(".category").textContent = documentRecord.category;
    fragment.querySelector(".source").textContent = documentRecord.source_name;
    const time = fragment.querySelector("time");
    time.textContent = formatTime(
      documentRecord.published_at || documentRecord.retrieved_at
    );
    time.dateTime = documentRecord.published_at || documentRecord.retrieved_at;
    fragment.querySelector("h3").textContent = documentRecord.title;
    fragment.querySelector("p").textContent =
      documentRecord.summary || "No source summary was provided.";
    const link = fragment.querySelector("a");
    const safeUrl = safeExternalUrl(documentRecord.url);
    if (safeUrl) link.href = safeUrl;
    else link.remove();
    elements.documentFeed.append(fragment);
  }
}

function renderSources(sources) {
  elements.sourceList.replaceChildren();
  for (const source of sources) {
    const card = document.createElement("div");
    card.className = "source-card";
    const title = document.createElement("strong");
    title.textContent = source.name;
    const details = document.createElement("span");
    details.textContent = `${source.document_count} documents · ${
      source.last_polled_at ? `polled ${formatTime(source.last_polled_at)}` : "awaiting first poll"
    }`;
    const health = document.createElement("i");
    health.className = `health${source.last_error ? " error" : ""}`;
    health.title = source.last_error || "Source healthy";
    card.append(title, details, health);
    elements.sourceList.append(card);
  }
}

function renderReputations(reputations) {
  elements.reputationList.replaceChildren();
  if (!reputations.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Waiting for mature independently checkable outcomes.";
    elements.reputationList.append(empty);
    return;
  }
  for (const reputation of reputations) {
    const card = document.createElement("div");
    card.className = "source-card reputation-card";
    const title = document.createElement("strong");
    title.textContent = reputation.publisher_label;
    const score = document.createElement("span");
    const evaluated = Number(reputation.evaluated_count ?? 0);
    const learned = Number(reputation.learned_credibility ?? 0);
    const salt = evaluated < 12
      ? `provisional (${evaluated}/12 factual checks) — large grain of salt`
      : learned >= 0.8
        ? "strong track record — small grain of salt"
        : learned >= 0.6
          ? "mixed-positive track record — moderate grain of salt"
          : "weak or mixed track record — large grain of salt";
    score.textContent =
      `${Math.round(reputation.baseline_credibility * 100)}% baseline → ` +
      `${Math.round(learned * 100)}% learned · ` +
      `${Math.round(reputation.reliability_lower_bound * 100)}–` +
      `${Math.round(reputation.reliability_upper_bound * 100)}% range`;
    const outcomes = document.createElement("small");
    outcomes.textContent =
      `${reputation.confirmed_count} confirmed · ` +
      `${reputation.contradicted_count} contradicted · ` +
      `${reputation.deleted_unverified_count} deleted/unverified · ` +
      `${reputation.early_confirmation_count} reported early · ${salt}`;
    outcomes.title = reputation.latest_outcome_reason ||
      "This measures corroborated factual reporting, not neutrality or framing.";
    card.append(title, score, outcomes);
    if (reputation.latest_outcome) {
      const audit = document.createElement("small");
      audit.textContent =
        `Latest check: ${reputation.latest_outcome} — ` +
        `${reputation.latest_outcome_reason}`;
      card.append(audit);
    }
    elements.reputationList.append(card);
  }
}

function renderForecasts(forecasts, calibration) {
  elements.forecastList.replaceChildren();
  const summary = document.createElement("p");
  summary.className = "empty";
  const brier = calibration?.brier_score;
  summary.textContent = `${calibration?.active ?? 0} active · ${calibration?.resolved ?? 0} resolved` +
    (Number.isFinite(brier) ? ` · Brier ${brier.toFixed(3)}` : " · calibration pending");
  elements.forecastList.append(summary);
  for (const forecast of forecasts.slice(0, 6)) {
    const card = document.createElement("div");
    card.className = "source-card";
    const title = document.createElement("strong");
    title.textContent = forecast.question;
    const detail = document.createElement("span");
    detail.textContent = `${Math.round(forecast.probability * 100)}% · ${forecast.status} · target ${formatTime(forecast.target_at)}`;
    const outcome = document.createElement("small");
    outcome.textContent = forecast.status === "resolved"
      ? `${forecast.actual_outcome ? "occurred" : "did not occur"} · Brier ${Number(forecast.brier_score).toFixed(3)}`
      : forecast.predicted_outcome;
    card.append(title, detail, outcome);
    elements.forecastList.append(card);
  }
}

async function refresh() {
  try {
    const categoryQuery = new URLSearchParams();
    if (selectedCategory) categoryQuery.set("category", selectedCategory);
    const category = categoryQuery.toString()
      ? `?${categoryQuery.toString()}`
      : "";
    const mapQuery = new URLSearchParams(categoryQuery);
    mapQuery.set("located", "1");
    mapQuery.set("limit", "200");
    const [overview, documents, sources, situations, mapSituations, briefing, reputations, forecasts] = await Promise.all([
      request("/api/intelligence/overview"),
      request(`/api/intelligence/documents${category}`),
      request("/api/intelligence/sources"),
      request(`/api/intelligence/situations${category}`),
      request(`/api/intelligence/situations?${mapQuery.toString()}`),
      request("/api/intelligence/briefing"),
      request("/api/intelligence/reputations"),
      request("/api/intelligence/forecasts")
    ]);
    renderOverview(overview);
    renderDocuments(documents.documents ?? []);
    renderSources(sources.sources ?? []);
    renderSituations(situations.situations ?? []);
    renderMap(mapSituations.situations ?? []);
    renderBriefing(briefing);
    renderReputations(reputations.reputations ?? []);
    renderForecasts(forecasts.forecasts ?? [], forecasts.calibration ?? {});
    setConnection(true);
  } catch (error) {
    setConnection(false);
  }
}

elements.categoryFilter.addEventListener("change", () => {
  selectedCategory = elements.categoryFilter.value;
  refresh();
});

elements.mapPriorityFilter.addEventListener("change", () => {
  mapPriority = elements.mapPriorityFilter.value;
  refresh();
});

refresh();
setInterval(refresh, 5000);
