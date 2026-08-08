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
  mapCountryFilter: document.querySelector("#map-country-filter"),
  mapTimeFilter: document.querySelector("#map-time-filter"),
  mapSeverityFilter: document.querySelector("#map-severity-filter"),
  mapAnalyze: document.querySelector("#map-analyze"),
  mapLayerToggles: [...document.querySelectorAll(".map-layer-toggle")],
  mapLabelsToggle: document.querySelector("#map-labels-toggle"),
  mapAircraftToggle: document.querySelector("#map-aircraft-toggle"),
  mapCommentaryToggle: document.querySelector("#map-commentary-toggle"),
  mapCommentary: document.querySelector("#map-commentary"),
  regionalAssessment: document.querySelector("#regional-assessment"),
  countryProfile: document.querySelector("#country-profile"),
  countryBreakdown: document.querySelector("#country-breakdown"),
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
  groundingCount: document.querySelector("#grounding-count"),
  directCheckCount: document.querySelector("#direct-check-count"),
  shadowModelCount: document.querySelector("#shadow-model-count"),
  epistemicHealth: document.querySelector("#epistemic-health"),
  documentTemplate: document.querySelector("#document-template"),
  situationTemplate: document.querySelector("#situation-template")
};

let selectedCategory = "";
let selectedSituationId = "";
let mapPriority = "priority";
let mapCountry = "";
let mapLabels = false;
let aircraft = [];
let intelligenceMap;
let situationMapLayer;
let aircraftMapLayer;
let countryMapLayer;
let nativeHazardLayer;
let nativeAnomalyLayer;
let countryRollups = new Map();
let countryLayers = new Map();
let commentaryTimer;
let viewportTimer;
let viewportRequest = 0;
let nativeFeatureSituationIds = new Set();
const commentaryCache = new Map();
const COUNTRY_BOUNDARIES_URL = "https://raw.githubusercontent.com/johan/world.geo.json/34c96bba9c07d2ceb30696c599bb51a5b939b20f/countries.geo.json";

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
  elements.verificationTaskCount.textContent = (
    `${overview.verification_tasks ?? 0} · ${overview.verification_results ?? 0} done`
  );
  elements.intelligenceGapCount.textContent = overview.intelligence_gaps ?? 0;
  elements.reasoningJobCount.textContent = overview.pending_reasoning_jobs ?? 0;
  elements.groundingCount.textContent = overview.claim_groundings ?? 0;
  elements.directCheckCount.textContent = overview.verification_observations ?? 0;
  elements.shadowModelCount.textContent = overview.shadow_ensemble_models ?? 0;
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
  if (!initializeMap()) return;
  const located = situations.filter((situation) =>
    Number.isFinite(situation.latitude) && Number.isFinite(situation.longitude)
  );
  const countryLocated = mapCountry ? located.filter((item) => item.location_country_name === mapCountry) : located;
  const displayed = selectMapSituations(countryLocated).filter((item) =>
    !nativeFeatureSituationIds.has(item.id) || hazardKind(item) === "other"
  );
  elements.mapStatus.textContent = displayed.length
    ? `${displayed.length} shown · ${countryLocated.length} in view · ${located.length} located`
    : "No located situations in this view";
  situationMapLayer.clearLayers();
  aircraftMapLayer.clearLayers();
  for (const group of clusterMapSituations(displayed, intelligenceMap.getZoom())) {
    const situation = group.items[0];
    if (group.items.length > 1) {
      const cluster = L.marker([group.latitude, group.longitude], {
        icon: L.divIcon({
          className: "map-cluster-wrap",
          html: `<span class="map-cluster map-symbol-${group.kind}">${group.items.length}</span>`,
          iconSize: [30, 30], iconAnchor: [15, 15]
        }), keyboard: true
      });
      cluster.bindTooltip(clusterTooltip(group.items), { sticky: true, className: "entity-map-tooltip" });
      cluster.on("click", () => {
        if (intelligenceMap.getZoom() < 8) intelligenceMap.setView([group.latitude, group.longitude], intelligenceMap.getZoom() + 2);
        else selectSituation(situation.id);
      });
      cluster.on("mouseover", () => scheduleCommentary("situation", situation.id));
      cluster.addTo(situationMapLayer);
      continue;
    }
    addSituationMarker(situation, group.kind);
  }
  if (elements.mapAircraftToggle.checked) renderAircraft();
}

function initializeMap() {
  if (intelligenceMap) return true;
  if (!window.L) {
    elements.mapStatus.textContent = "Interactive map library unavailable";
    return false;
  }
  intelligenceMap = L.map(elements.worldMap, {
    center: [20, 0], zoom: 2, minZoom: 2, maxZoom: 11,
    worldCopyJump: true, zoomControl: true, preferCanvas: true
  });
  L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
    maxZoom: 20,
    subdomains: "abcd",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a> &copy; <a href="https://carto.com/attributions">CARTO</a>'
  }).addTo(intelligenceMap);
  countryMapLayer = L.layerGroup().addTo(intelligenceMap);
  nativeHazardLayer = L.layerGroup().addTo(intelligenceMap);
  nativeAnomalyLayer = L.layerGroup().addTo(intelligenceMap);
  situationMapLayer = L.layerGroup().addTo(intelligenceMap);
  aircraftMapLayer = L.layerGroup().addTo(intelligenceMap);
  intelligenceMap.on("zoomend", () => {
    renderMap(lastMapSituations);
    scheduleViewportLoad();
  });
  intelligenceMap.on("moveend", scheduleViewportLoad);
  loadCountryBoundaries();
  scheduleViewportLoad();
  return true;
}

async function loadCountryBoundaries() {
  try {
    const response = await fetch(COUNTRY_BOUNDARIES_URL, { cache: "force-cache" });
    if (!response.ok) throw new Error(`Country boundaries ${response.status}`);
    const geojson = await response.json();
    const boundaries = L.geoJSON(geojson, {
      style: () => ({ color: "#74aaa5", weight: .65, opacity: .55, fillColor: "#163238", fillOpacity: .08 }),
      onEachFeature: (feature, layer) => {
        const name = feature.properties?.name || "Unknown territory";
        countryLayers.set(normalizeCountry(name), layer);
        layer.bindTooltip(() => countryTooltip(name), { sticky: true, className: "entity-map-tooltip" });
        layer.on("mouseover", () => {
          layer.setStyle({ weight: 1.5, color: "#8cf4e8", fillOpacity: .18 });
          scheduleCommentary("country", matchingCountryName(name) || name);
        });
        layer.on("mouseout", () => boundaries.resetStyle(layer));
        layer.on("click", () => {
          mapCountry = matchingCountryName(name);
          elements.mapCountryFilter.value = mapCountry;
          intelligenceMap.fitBounds(layer.getBounds(), { padding: [20, 20] });
          renderMap(lastMapSituations);
          loadCountryProfile(mapCountry || name);
        });
      }
    });
    boundaries.addTo(countryMapLayer);
  } catch (error) {
    elements.mapStatus.textContent += " · country boundaries unavailable";
  }
}

function clusterMapSituations(situations, zoom = 2) {
  const buckets = new Map();
  const cellDegrees = Math.max(.4, 22 / Math.pow(2, Math.max(0, zoom - 2)));
  for (const item of situations) {
    const kind = hazardKind(item);
    const key = `${kind}:${Math.floor((item.longitude + 180) / cellDegrees)}:${Math.floor((item.latitude + 90) / cellDegrees)}`;
    const bucket = buckets.get(key) ?? [];
    bucket.push(item); buckets.set(key, bucket);
  }
  return [...buckets.values()].map((items) => {
    items.sort((a, b) => mapPriorityScore(b) - mapPriorityScore(a));
    return { items, kind: hazardKind(items[0]), longitude: items.reduce((sum, item) => sum + item.longitude, 0) / items.length, latitude: items.reduce((sum, item) => sum + item.latitude, 0) / items.length };
  });
}

function addSituationMarker(situation, kind) {
  const coordinates = [situation.latitude, situation.longitude];
  if (kind === "wildfire") {
    const precisionKm = Math.max(8, Math.min(180, Number(situation.location_precision_km || 35)));
    L.circle(coordinates, { radius: precisionKm * 1000, className: "wildfire-area", color: "#ef5038", weight: 1, fillColor: "#dc321e", fillOpacity: .18, interactive: false }).addTo(situationMapLayer);
  }
  const marker = L.marker(coordinates, {
    icon: L.divIcon({
      className: "map-symbol-wrap",
      html: `<span class="map-symbol map-symbol-${kind}" aria-hidden="true">${hazardGlyph(kind)}</span>`,
      iconSize: [24, 24], iconAnchor: [12, 12]
    }), keyboard: true,
    title: situation.title
  });
  marker.bindTooltip(situationTooltip(situation), { sticky: !mapLabels, permanent: mapLabels, direction: "top", className: mapLabels ? "map-place-label" : "entity-map-tooltip" });
  marker.on("mouseover", () => scheduleCommentary("situation", situation.id));
  marker.on("click", () => selectSituation(situation.id));
  marker.addTo(situationMapLayer);
}

function hazardGlyph(kind) {
  return { wildfire: "▲", earthquake: "◆", flood: "≈", storm: "●", volcano: "⬟", other: "·" }[kind] || "·";
}

function situationTooltip(situation) {
  const node = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = situation.title;
  const detail = document.createElement("span");
  detail.textContent = `${situation.category} · ${Math.round(Number(situation.confidence || 0) * 100)}% confidence · ${situation.evidence_count || 0} evidence`;
  node.append(title, detail);
  return node;
}

function clusterTooltip(items) {
  const node = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = `${items.length} nearby ${hazardKind(items[0])} situations`;
  const detail = document.createElement("span");
  detail.textContent = items.slice(0, 3).map((item) => item.title).join(" · ");
  node.append(title, detail);
  return node;
}

function hazardKind(situation) {
  const value = `${situation.category || ""} ${situation.title || ""}`.toLowerCase();
  if (/wildfire|wildfires|fire alert|vegetation fire/.test(value)) return "wildfire";
  if (/earthquake|seismic|\beq\b/.test(value)) return "earthquake";
  if (/flood|inundation/.test(value)) return "flood";
  if (/storm|cyclone|hurricane|typhoon|tornado|weather-alert/.test(value)) return "storm";
  return "other";
}

function renderAircraft() {
  for (const state of aircraft) {
    if (!Number.isFinite(state.latitude) || !Number.isFinite(state.longitude)) continue;
    const heading = Number(state.heading_degrees || 0);
    const marker = L.marker([state.latitude, state.longitude], {
      icon: L.divIcon({ className: "aircraft-marker-wrap", html: `<span class="aircraft-marker" style="transform:rotate(${heading}deg)">▲</span>`, iconSize: [20, 20], iconAnchor: [10, 10] }),
      keyboard: true, title: state.callsign || state.icao24
    });
    const altitude = Number.isFinite(state.altitude_m) ? `${Math.round(state.altitude_m)} m` : "altitude unavailable";
    marker.bindTooltip(`${state.callsign || state.icao24} · ${altitude} · ADSB.lol`, { sticky: true, className: "entity-map-tooltip" });
    marker.addTo(aircraftMapLayer);
  }
}

function renderCountries(countries) {
  countryRollups = new Map(countries.map((item) => [normalizeCountry(item.country_name), item]));
  const current = elements.mapCountryFilter.value;
  elements.mapCountryFilter.replaceChildren(new Option("All countries", ""));
  for (const country of countries) elements.mapCountryFilter.add(new Option(`${country.country_name} · ${country.active} active`, country.country_name));
  elements.mapCountryFilter.value = current;
  elements.countryBreakdown.replaceChildren();
  for (const country of countries.slice(0, 12)) {
    const button = document.createElement("button"); button.type = "button"; button.className = "country-row";
    button.textContent = `${country.country_name}  ${country.active} active · ${country.situations} total`;
    button.addEventListener("click", () => {
      elements.mapCountryFilter.value = country.country_name; mapCountry = country.country_name;
      const layer = countryLayers.get(normalizeCountry(country.country_name));
      if (layer) intelligenceMap.fitBounds(layer.getBounds(), { padding: [20, 20] });
      renderMap(lastMapSituations);
      loadCountryProfile(country.country_name);
    });
    elements.countryBreakdown.append(button);
  }
}
let lastMapSituations = [];

function normalizeCountry(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
}

function matchingCountryName(boundaryName) {
  const normalized = normalizeCountry(boundaryName);
  const aliases = { unitedstatesofamerica: "unitedstates", russianfederation: "russia", syrianarabrepublic: "syria", iranislamicrepublicof: "iran" };
  const wanted = aliases[normalized] || normalized;
  return countryRollups.get(wanted)?.country_name || "";
}

function countryTooltip(name) {
  const rollup = countryRollups.get(normalizeCountry(matchingCountryName(name) || name));
  const node = document.createElement("div");
  const title = document.createElement("strong"); title.textContent = name;
  const detail = document.createElement("span");
  detail.textContent = rollup ? `${rollup.active} active · ${rollup.contested} contested · ${rollup.situations} total` : "No country-attributed situations in this view";
  node.append(title, detail);
  return node;
}

function selectedHazardLayers() {
  return elements.mapLayerToggles.filter((item) => item.checked).map((item) => item.value);
}

function mapSince() {
  const days = Math.max(1, Number(elements.mapTimeFilter.value || 7));
  return new Date(Date.now() - days * 86_400_000).toISOString();
}

function viewportQuery() {
  const bounds = intelligenceMap.getBounds();
  return new URLSearchParams({
    bbox: [bounds.getWest(), bounds.getSouth(), bounds.getEast(), bounds.getNorth()].join(","),
    layers: selectedHazardLayers().join(","),
    since: mapSince(),
    severity: elements.mapSeverityFilter.value || "0",
    zoom: String(intelligenceMap.getZoom()),
    limit: intelligenceMap.getZoom() <= 5 ? "600" : "1800",
    cell_limit: "800"
  });
}

function scheduleViewportLoad() {
  if (!intelligenceMap) return;
  clearTimeout(viewportTimer);
  viewportTimer = setTimeout(loadViewportFeatures, 220);
}

async function loadViewportFeatures() {
  const requestId = ++viewportRequest;
  try {
    const payload = await request(`/api/intelligence/map/features?${viewportQuery()}`);
    if (requestId !== viewportRequest) return;
    renderNativeFeatures(payload);
  } catch (error) {
    if (requestId === viewportRequest) elements.mapStatus.textContent += " · hazard layer unavailable";
  }
}

function renderNativeFeatures(payload) {
  nativeHazardLayer.clearLayers();
  nativeAnomalyLayer.clearLayers();
  nativeFeatureSituationIds = new Set();
  const zoom = intelligenceMap.getZoom();
  const features = payload.features || [];
  const aggregateWildfires = zoom <= 5;
  for (const feature of features) {
    if (feature.situation_id) nativeFeatureSituationIds.add(feature.situation_id);
    if (aggregateWildfires && feature.feature_type === "wildfire") continue;
    addNativeFeature(feature);
  }
  if (aggregateWildfires) {
    for (const cell of payload.cells || []) {
      if (cell.feature_type !== "wildfire") continue;
      const radius = Math.max(5, Math.min(19, 4 + Math.sqrt(Number(cell.detection_count || 1)) * 1.7));
      const marker = L.circleMarker([cell.centroid_latitude, cell.centroid_longitude], {
        radius, className: "native-cell native-cell-wildfire", color: "#ff8169",
        weight: 1, fillColor: "#dd3c25", fillOpacity: .42
      });
      marker.bindTooltip(`${cell.detection_count} wildfire detections · max ${Math.round(Number(cell.max_severity || 0) * 100)}% severity · zoom in for observations`, { sticky: true, className: "entity-map-tooltip" });
      marker.addTo(nativeHazardLayer);
    }
  }
  for (const anomaly of payload.anomalies || []) {
    if (!Number.isFinite(anomaly.centroid_latitude) || !Number.isFinite(anomaly.centroid_longitude)) continue;
    L.circleMarker([anomaly.centroid_latitude, anomaly.centroid_longitude], {
      radius: 12, className: "geo-anomaly", color: "#fff198", weight: 2,
      fillColor: "transparent", fillOpacity: 0
    }).bindTooltip(`Change signal: ${String(anomaly.anomaly_type || "anomaly").replaceAll("-", " ")} · ${Math.round(Number(anomaly.confidence || 0) * 100)}% confidence`, { sticky: true, className: "entity-map-tooltip" }).addTo(nativeAnomalyLayer);
  }
  renderMap(lastMapSituations);
  const rendered = features.length + (payload.cells || []).length;
  elements.mapStatus.textContent = `${rendered} native observations/cells · ${selectMapSituations(lastMapSituations).length} situation candidates`;
}

function addNativeFeature(feature) {
  const kind = feature.feature_type || "other";
  const geometry = feature.geometry && feature.geometry.coordinates ? feature.geometry : {
    type: "Point", coordinates: [feature.centroid_longitude, feature.centroid_latitude]
  };
  const layer = L.geoJSON({ type: "Feature", geometry, properties: {} }, {
    style: () => ({
      className: `native-geometry native-${kind}`, color: hazardColor(kind), weight: 2,
      fillColor: hazardColor(kind), fillOpacity: kind === "wildfire" ? .24 : .15
    }),
    pointToLayer: (_item, latlng) => L.marker(latlng, {
      icon: L.divIcon({
        className: "map-symbol-wrap native-symbol-wrap",
        html: `<span class="map-symbol map-symbol-${kind}" aria-hidden="true">${hazardGlyph(kind)}</span>`,
        iconSize: [24, 24], iconAnchor: [12, 12]
      }), keyboard: true
    })
  });
  const tooltip = document.createElement("div");
  const title = document.createElement("strong");
  title.textContent = `${kind.replaceAll("-", " ")} · ${feature.severity_label || `${Math.round(Number(feature.severity || 0) * 100)}% severity`}`;
  const detail = document.createElement("span");
  detail.textContent = `${feature.source_id} · observed ${formatTime(feature.observed_at)}${feature.country_name ? ` · ${feature.country_name}` : ""}`;
  tooltip.append(title, detail);
  layer.bindTooltip(tooltip, { sticky: true, className: "entity-map-tooltip" });
  layer.on("mouseover", () => scheduleCommentary("feature", feature.id));
  layer.on("click", () => {
    if (feature.situation_id) selectSituation(feature.situation_id);
  });
  layer.addTo(nativeHazardLayer);
}

function hazardColor(kind) {
  return { wildfire: "#f04b35", earthquake: "#efa24a", flood: "#3a9de6", storm: "#a373e5", volcano: "#df6e3d" }[kind] || "#42c9ba";
}

async function analyzeVisibleRegion() {
  elements.regionalAssessment.hidden = false;
  elements.regionalAssessment.textContent = "Entity is assembling an evidence-linked regional assessment…";
  try {
    const payload = await request(`/api/intelligence/map/regional-assessment?${viewportQuery()}`);
    elements.regionalAssessment.replaceChildren();
    const title = document.createElement("strong"); title.textContent = payload.headline;
    const body = document.createElement("span"); body.textContent = payload.assessment;
    const note = document.createElement("small");
    note.textContent = `${payload.evidence?.length || 0} linked observations · ${payload.method}`;
    elements.regionalAssessment.append(title, body);
    for (const uncertainty of payload.uncertainties || []) {
      const warning = document.createElement("em"); warning.textContent = uncertainty;
      elements.regionalAssessment.append(warning);
    }
    elements.regionalAssessment.append(note);
  } catch (error) {
    elements.regionalAssessment.textContent = "Entity could not assemble this regional assessment.";
  }
}

async function loadCountryProfile(country) {
  if (!country) {
    elements.countryProfile.hidden = true;
    return;
  }
  elements.countryProfile.hidden = false;
  elements.countryProfile.textContent = `Loading the evidence profile for ${country}…`;
  try {
    const payload = await request(`/api/intelligence/country-profile?country=${encodeURIComponent(country)}`);
    const profile = payload.profile || {};
    elements.countryProfile.replaceChildren();
    const title = document.createElement("strong"); title.textContent = `${profile.country_name} evidence profile`;
    const body = document.createElement("span");
    body.textContent = `${profile.active_situations || 0} active situations · ${profile.contested_situations || 0} contested · ${profile.active_hazards || 0} native hazards · ${profile.forecast_count || 0} active forecasts`;
    const gaps = document.createElement("small");
    gaps.textContent = (profile.coverage_gaps || []).length ? `Coverage gaps: ${profile.coverage_gaps.join(", ")}` : "No configured hazard-layer gaps detected.";
    elements.countryProfile.append(title, body, gaps);
  } catch (error) {
    elements.countryProfile.textContent = `A materialized profile for ${country} is not available yet; the bounded backfill is still learning it.`;
  }
}

function scheduleCommentary(type, value) {
  if (!elements.mapCommentaryToggle.checked) return;
  clearTimeout(commentaryTimer);
  commentaryTimer = setTimeout(() => loadMapCommentary(type, value), 450);
}

async function loadMapCommentary(type, value) {
  const key = `${type}:${value}`;
  elements.mapCommentary.hidden = false;
  elements.mapCommentary.textContent = "Entity is reading the current evidence…";
  try {
    let payload = commentaryCache.get(key);
    if (!payload) {
      const query = new URLSearchParams({ type });
      query.set(type === "country" ? "country" : "id", value);
      payload = await request(`/api/intelligence/map-commentary?${query}`);
      commentaryCache.set(key, payload);
    }
    elements.mapCommentary.replaceChildren();
    const title = document.createElement("strong"); title.textContent = payload.headline;
    const body = document.createElement("span"); body.textContent = payload.commentary;
    const note = document.createElement("small");
    note.textContent = `Evidence-based ${payload.basis || "readout"}${Number.isFinite(payload.confidence) ? ` · ${Math.round(payload.confidence * 100)}% situation confidence` : ""}`;
    elements.mapCommentary.append(title, body, note);
  } catch (error) {
    elements.mapCommentary.textContent = "Entity could not assemble commentary for this map feature.";
  }
}

function selectMapSituations(situations) {
  if (mapPriority === "all") return situations;
  const active = situations.filter((situation) => situation.status === "active");
  if (mapPriority === "active") return active.slice(0, 75);
  const ranked = active
    .map((situation) => ({ situation, score: mapPriorityScore(situation) }))
    .sort((left, right) => right.score - left.score)
    .map((item) => item.situation);
  const selected = [];
  const counts = new Map();
  for (const situation of ranked) {
    const kind = hazardKind(situation);
    if ((counts.get(kind) || 0) >= 10) continue;
    selected.push(situation); counts.set(kind, (counts.get(kind) || 0) + 1);
    if (selected.length === 30) break;
  }
  return selected;
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
    const place = situation.location_label || situation.location_country_name || "reported coordinates";
    label.textContent = `${place} · ${Math.round((situation.location_confidence || 0) * 100)}% geographic confidence · ${situation.latitude.toFixed(3)}, ${situation.longitude.toFixed(3)}`;
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
    if ((forecast.components ?? []).length) {
      const components = document.createElement("small");
      components.textContent = "Probability inputs: " + forecast.components
        .map((item) => `${item.component} ${Math.round(item.probability * 100)}% × ${Math.round(item.weight * 100)}%`)
        .join(" · ");
      card.append(components);
    }
    elements.forecastList.append(card);
  }
}

function renderEpistemicHealth(health) {
  elements.epistemicHealth.replaceChildren();
  const card = (titleText, detailText) => {
    const node = document.createElement("div");
    node.className = "source-card";
    const title = document.createElement("strong");
    title.textContent = titleText;
    const detail = document.createElement("span");
    detail.textContent = detailText;
    node.append(title, detail);
    return node;
  };
  const ready = (health.verification_targets ?? []).find((item) => item.target_status === "ready")?.count ?? 0;
  const unresolvable = (health.verification_targets ?? []).find((item) => item.target_status === "unresolvable")?.count ?? 0;
  const targetSummary = card("Verification funnel", `${ready} queryable · ${unresolvable} unresolvable`);
  const calibration = health.calibration ?? {};
  const forecastSummary = card("V2 forecast maturity", `${calibration.v2_resolved ?? 0} resolved · ${Math.round((calibration.v2_resolution_coverage ?? 0) * 100)}% resolution coverage`);
  const model = (health.models ?? [])[0];
  const modelSummary = card("Learned ensemble", model ? `${model.status} · ${model.sample_count} training samples` : "awaiting independently resolved forecasts");
  elements.epistemicHealth.append(targetSummary, forecastSummary, modelSummary);
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
    const [overview, documents, sources, situations, geography, briefing, reputations, forecasts, epistemicHealth, aircraftResponse] = await Promise.all([
      request("/api/intelligence/overview"),
      request(`/api/intelligence/documents${category}`),
      request("/api/intelligence/sources"),
      request(`/api/intelligence/situations${category}`),
      request(`/api/intelligence/geography?${mapQuery.toString()}`),
      request("/api/intelligence/briefing"),
      request("/api/intelligence/reputations"),
      request("/api/intelligence/forecasts"),
      request("/api/intelligence/epistemic-health"),
      request("/api/intelligence/aircraft?limit=300")
    ]);
    renderOverview(overview);
    renderDocuments(documents.documents ?? []);
    renderSources(sources.sources ?? []);
    renderSituations(situations.situations ?? []);
    lastMapSituations = geography.situations ?? [];
    aircraft = aircraftResponse.aircraft ?? [];
    renderCountries(geography.countries ?? []);
    renderMap(lastMapSituations);
    scheduleViewportLoad();
    renderBriefing(briefing);
    renderReputations(reputations.reputations ?? []);
    renderForecasts(forecasts.forecasts ?? [], forecasts.calibration ?? {});
    renderEpistemicHealth(epistemicHealth);
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
elements.mapCountryFilter.addEventListener("change", () => {
  mapCountry = elements.mapCountryFilter.value;
  const layer = countryLayers.get(normalizeCountry(mapCountry));
  if (layer && mapCountry) intelligenceMap.fitBounds(layer.getBounds(), { padding: [20, 20] });
  else if (intelligenceMap && !mapCountry) intelligenceMap.setView([20, 0], 2);
  renderMap(lastMapSituations);
  loadCountryProfile(mapCountry);
});
elements.mapLabelsToggle.addEventListener("change", () => { mapLabels = elements.mapLabelsToggle.checked; renderMap(lastMapSituations); });
elements.mapAircraftToggle.addEventListener("change", () => renderMap(lastMapSituations));
elements.mapTimeFilter.addEventListener("change", scheduleViewportLoad);
elements.mapSeverityFilter.addEventListener("change", scheduleViewportLoad);
for (const toggle of elements.mapLayerToggles) toggle.addEventListener("change", scheduleViewportLoad);
elements.mapAnalyze.addEventListener("click", analyzeVisibleRegion);
elements.mapCommentaryToggle.addEventListener("change", () => {
  clearTimeout(commentaryTimer);
  if (!elements.mapCommentaryToggle.checked) {
    elements.mapCommentary.hidden = true;
    elements.mapCommentary.replaceChildren();
  } else {
    elements.mapCommentary.hidden = false;
    elements.mapCommentary.textContent = "Hover over a country or situation for Entity's evidence-based readout.";
  }
});

refresh();
setInterval(refresh, 5000);
