let overview;
let selectedSide = 'blue';
let debugStatus;
let debugCatalogs = {ground: {}, air: {presets: {}}};
let situationMap;
let situationLayers;
let situationFitted = false;
let situationBounds = [];
let selectedSituationGroup = null;
const situationSymbolCache = new Map();

function activatePage(page) {
  const button = document.querySelector(`.tab[data-page="${page}"]`);
  const section = document.querySelector(`.page[data-page="${page}"]`);
  if (!button || !section) return;
  document.querySelectorAll('.tab,.page').forEach(element => element.classList.remove('active'));
  button.classList.add('active');
  section.classList.add('active');
  if (page === 'situation' && situationMap) {
    setTimeout(() => situationMap.invalidateSize(), 0);
  }
}

document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => {
  activatePage(button.dataset.page);
  history.replaceState(null, '', `#${button.dataset.page}`);
}));

document.querySelectorAll('[data-side]').forEach(button => button.addEventListener('click', () => {
  selectedSide = button.dataset.side;
  document.querySelectorAll('[data-side]').forEach(item => item.classList.toggle('active', item === button));
  renderActions();
}));

document.getElementById('new-game').addEventListener('click', async () => {
  const button = document.getElementById('new-game');
  button.disabled = true;
  const response = await fetch('/api/campaign/new', {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
  });
  if (!response.ok) button.disabled = false;
  await refresh();
});

function updateDebugPresets() {
  const side = document.getElementById('debug-side').value;
  const kind = document.getElementById('debug-kind').value;
  const entries = kind === 'air'
    ? debugCatalogs.air?.presets?.[side] || {}
    : debugCatalogs.ground?.[side] || {};
  const select = document.getElementById('debug-preset');
  select.replaceChildren(...Object.entries(entries).map(([id, entry]) =>
    new Option(`${entry.label || id}${entry.role ? ` · ${entry.role}` : ''}`, id)));
  document.getElementById('debug-altitude-field').hidden = kind !== 'air';
  if (kind === 'air' && entries[select.value]?.altitude_m) {
    document.getElementById('debug-altitude').value = entries[select.value].altitude_m;
  }
}

document.getElementById('debug-side').addEventListener('change', updateDebugPresets);
document.getElementById('debug-kind').addEventListener('change', updateDebugPresets);
document.getElementById('debug-preset').addEventListener('change', () => {
  const side = document.getElementById('debug-side').value;
  const preset = debugCatalogs.air?.presets?.[side]?.[document.getElementById('debug-preset').value];
  if (preset?.altitude_m) document.getElementById('debug-altitude').value = preset.altitude_m;
});

document.getElementById('debug-spawn').addEventListener('submit', async event => {
  event.preventDefault();
  const kind = document.getElementById('debug-kind').value;
  const feedback = document.getElementById('debug-feedback');
  const button = event.submitter;
  const payload = {
    side: document.getElementById('debug-side').value,
    [kind === 'air' ? 'preset' : 'template']: document.getElementById('debug-preset').value,
    name: document.getElementById('debug-name').value.trim() || undefined,
    lat: Number(document.getElementById('debug-lat').value),
    lon: Number(document.getElementById('debug-lon').value)
  };
  if (kind === 'air') payload.altitude_m = Number(document.getElementById('debug-altitude').value);
  button.disabled = true;
  feedback.className = '';
  feedback.textContent = 'Sending spawn request…';
  try {
    const response = await fetch(kind === 'air' ? '/api/spawn-air' : '/api/spawn', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Spawn failed');
    feedback.className = 'success';
    feedback.textContent = `${result.name} accepted by DCS.`;
    await refresh();
  } catch (error) {
    feedback.className = 'error';
    feedback.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

function updateDebugGroups() {
  const side = document.getElementById('order-side').value;
  const coalition = side === 'blue' ? 2 : 1;
  const groups = (debugStatus?.snapshot?.groups || []).filter(group =>
    group.coalition === coalition && group.units?.length);
  document.getElementById('order-group').replaceChildren(...groups.map(group =>
    new Option(`${group.name} · ${group.category === 0 ? 'air' : 'ground'} · ${group.units.length}`, group.name)));
  const airbases = (debugStatus?.snapshot?.airbases || []).filter(base => base.coalition === coalition);
  document.getElementById('order-airbase').replaceChildren(...airbases.map(base => new Option(base.name, base.name)));
}

document.getElementById('order-side').addEventListener('change', updateDebugGroups);
document.getElementById('debug-order').addEventListener('submit', async event => {
  event.preventDefault();
  const feedback = document.getElementById('order-feedback');
  const button = event.submitter;
  const operation = document.getElementById('order-operation').value;
  const payload = {
    side: document.getElementById('order-side').value,
    group: document.getElementById('order-group').value,
    op: operation,
    lat: Number(document.getElementById('order-lat').value),
    lon: Number(document.getElementById('order-lon').value),
    altitude_m: Number(document.getElementById('order-altitude').value),
    mission_type: document.getElementById('order-mission').value,
    mode: document.getElementById('order-roe').value,
    airbase: document.getElementById('order-airbase').value
  };
  button.disabled = true;
  feedback.className = '';
  feedback.textContent = 'Sending order…';
  try {
    const response = await fetch('/api/orders', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
    });
    const result = await response.json();
    if (!response.ok || !result.ok) throw new Error(result.error || 'Order failed');
    feedback.className = 'success';
    feedback.textContent = `${result.operation} accepted for ${result.group}.`;
    await refresh();
  } catch (error) {
    feedback.className = 'error';
    feedback.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

function initializeSituationMap() {
  if (situationMap || !window.L) return;
  situationMap = L.map('situation-map', {preferCanvas: true, zoomControl: false}).setView([42.3, 41.8], 7);
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 17,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>'
  }).addTo(situationMap);
  situationLayers = {
    objectives: L.layerGroup().addTo(situationMap),
    missions: L.layerGroup().addTo(situationMap),
    forces: L.layerGroup().addTo(situationMap),
    airbases: L.layerGroup().addTo(situationMap),
    statics: L.layerGroup().addTo(situationMap)
  };
  L.control.layers(null, {
    Objectives: situationLayers.objectives,
    Missions: situationLayers.missions,
    Forces: situationLayers.forces,
    Airbases: situationLayers.airbases,
    Statics: situationLayers.statics
  }, {position: 'bottomright'}).addTo(situationMap);
  L.control.zoom({position: 'bottomright'}).addTo(situationMap);
  const FitControl = L.Control.extend({
    options: {position: 'bottomright'},
    onAdd() {
      const container = L.DomUtil.create('div', 'leaflet-bar leaflet-control-fit');
      const button = L.DomUtil.create('a', '', container);
      button.href = '#';
      button.title = 'Fit campaign and forces';
      button.setAttribute('aria-label', button.title);
      button.innerHTML = '&#8982;';
      L.DomEvent.disableClickPropagation(container);
      L.DomEvent.on(button, 'click', event => {
        L.DomEvent.preventDefault(event);
        fitSituationMap();
      });
      return container;
    }
  });
  new FitControl().addTo(situationMap);
  situationMap.on('zoomend', () => {
    if (debugStatus?.snapshot && situationLayers) {
      renderSituationForces(debugStatus.snapshot);
    }
  });
  situationMap.on('click', () => {
    selectedSituationGroup = null;
    situationLayers.missions.clearLayers();
  });
}

function fitSituationMap() {
  if (situationMap && situationBounds.length) {
    situationMap.fitBounds(situationBounds, {padding: [45, 45], maxZoom: 10});
  }
}

function escapeHtml(value) {
  const text = document.createElement('span');
  text.textContent = String(value);
  return text.innerHTML;
}

function situationSymbolCode(group) {
  const affiliation = ({2: 'F', 1: 'H', 0: 'N'})[group.coalition] || 'U';
  const category = ({0: 'APMF------', 1: 'APMH------', 2: 'GPU-------',
    3: 'SP--------', 4: 'GPEV------'})[group.category] || 'ZP--------';
  return `S${affiliation}${category}---`;
}

function situationVehicleKind(group, unit) {
  if (group.category === 3) return 'ship';
  if (group.category === 4) return 'train';
  const type = String(unit.type || '').toLowerCase();
  if (/infantry|soldier|paratrooper|manpad/.test(type)) return 'infantry';
  if (/radar|\b(sr|tr)\b|9s18|1l13|55g6/.test(type)) return 'radar';
  if (/avenger|strela|tunguska|shilka|vulcan|gepard|bofors|zsu|zu-23|\bln\b|sam|patriot|hawk|buk|tor 9|osa 9/.test(type) && !/\b(cc|pcp)\b/.test(type)) return 'air-defense';
  if (/abrams|^m[- ]?1(?:a| |$)|^t[- ]?(?:55|62|64|72|80|90)|leopard|challenger|leclerc|merkava|chieftain/.test(type)) return 'tank';
  if (/bradley|^m[- ]?2(?:a| |$)|bmp|bmd|btr|aav7|lav|stryker|warrior|marder|m113|mt-lb/.test(type)) return 'armor';
  if (/howitzer|mortar|mlrs|grad|smerch|uragan|^2s|^m[- ]?109(?:a| |$)/.test(type)) return 'artillery';
  if (/tanker|^atz|fuel/.test(type)) return 'tanker';
  if (/truck|ural|818|hemtt|kamaz|kraz|zil|gaz|uaz|hmmwv|hummer|land rover|cckw/.test(type)) return 'truck';
  return 'vehicle';
}

function situationVehicleArtwork(kind, coalition) {
  const shapes = {
    tank: '<path d="M5 24h33l5 5-5 6H7l-5-6zM13 23l3-9h15l5 9M30 16h16v4H30"/><path d="M9 29h26"/>',
    armor: '<path d="M4 23l9-8h21l10 10v6H4zM21 15v-5h10v5M30 11h13"/><circle cx="12" cy="32" r="4"/><circle cx="24" cy="32" r="4"/><circle cx="36" cy="32" r="4"/>',
    truck: '<path d="M3 13h25v17H3zM28 19h10l7 8v3H28zM33 21v5h9"/><circle cx="11" cy="32" r="4"/><circle cx="36" cy="32" r="4"/>',
    tanker: '<rect x="3" y="14" width="26" height="14" rx="6"/><path d="M29 19h9l7 8v3H3M33 21v5h9"/><circle cx="11" cy="32" r="4"/><circle cx="36" cy="32" r="4"/>',
    'air-defense': '<path d="M5 26h34l4 5-5 4H7l-4-4zM19 25v-8M11 19L31 5l4 5-20 14zM20 22L40 8l4 5-20 14z"/>',
    radar: '<path d="M5 27h35v7H5zM24 26V15M13 6q-3 19 17 13zM25 11l9-7M35 4q9 4 7 13"/><circle cx="12" cy="34" r="3"/><circle cx="34" cy="34" r="3"/>',
    infantry: '<circle cx="24" cy="7" r="4"/><path d="M20 14h8l3 13h-6l8 13h-6l-6-11-5 11h-6l8-16zM20 16l-7 9M27 16l8 8M31 15l7 16"/>',
    artillery: '<path d="M10 27L38 6l4 5-28 21zM17 28L5 37M25 24l15 13"/><circle cx="20" cy="30" r="7"/>',
    ship: '<path d="M3 26h42l-8 10H12zM15 25V15h17v10M23 15V5M23 8h12M5 40q5-5 10 0t10 0 10 0 10 0"/>',
    train: '<rect x="10" y="5" width="28" height="29" rx="5"/><path d="M14 10h20v10H14zM15 34l-5 8M33 34l5 8M12 39h24"/><circle cx="17" cy="27" r="2"/><circle cx="31" cy="27" r="2"/>',
    vehicle: '<path d="M4 25l6-11h26l8 11v7H4zM13 17h9v8H9M26 17h8l5 8H26"/><circle cx="12" cy="33" r="4"/><circle cx="36" cy="33" r="4"/>'
  };
  const color = ({2: '#8ed8f8', 1: '#ff8b8b', 0: '#b9e5bd'})[coalition] || '#f5d879';
  return {
    html: `<svg xmlns="http://www.w3.org/2000/svg" width="38" height="36" viewBox="0 0 48 46" aria-hidden="true"><g fill="${color}" stroke="#14212b" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round">${shapes[kind]}</g></svg>`,
    size: [38, 36], anchor: [19, 18]
  };
}

function situationUnitIcon(group, unit, count = group.units.length) {
  const isVehicle = [2, 3, 4].includes(group.category);
  const kind = isVehicle ? situationVehicleKind(group, unit) : null;
  const code = isVehicle ? `${group.coalition}:${kind}` : situationSymbolCode(group);
  let artwork = situationSymbolCache.get(code);
  if (!artwork) {
    if (isVehicle) {
      artwork = situationVehicleArtwork(kind, group.coalition);
    } else if (window.ms) {
      const symbol = new ms.Symbol(code, {size: 24});
      const size = symbol.getSize();
      const anchor = symbol.getAnchor();
      artwork = {html: symbol.asSVG(), size: [size.width, size.height], anchor: [anchor.x, anchor.y]};
    } else {
      const side = group.coalition === 2 ? 'blue' : 'red';
      const glyph = group.category === 0 || group.category === 1 ? '&#9992;' : '?';
      artwork = {html: `<span class="symbol-fallback ${side}">${glyph}</span>`, size: [32, 32], anchor: [16, 16]};
    }
    situationSymbolCache.set(code, artwork);
  }
  return L.divIcon({
    className: 'unit-marker', iconSize: artwork.size, iconAnchor: artwork.anchor,
    html: `<span class="unit-symbol">${artwork.html}</span>${count > 1 ? `<span class="unit-count">${count}</span>` : ''}`
  });
}

function renderSituationForces(snapshot) {
  situationLayers.forces.clearLayers();
  const expanded = situationMap.getZoom() >= 15;
  (snapshot?.groups || []).forEach(group => {
    const units = (group.units || []).filter(unit =>
      Number.isFinite(unit.lat) && Number.isFinite(unit.lon));
    if (!units.length || ![1, 2].includes(group.coalition)) return;
    const side = group.coalition === 2 ? 'blue' : 'red';
    const kind = ({0: 'aircraft', 1: 'helicopter', 2: 'ground', 3: 'ship', 4: 'train'})[group.category] || 'group';
    const visibleUnits = expanded ? units : [units[0]];
    visibleUnits.forEach(unit => {
      const count = expanded ? 1 : units.length;
      const icon = situationUnitIcon(group, unit, count);
      const title = expanded
        ? `${escapeHtml(unit.type || unit.name)}<br>${escapeHtml(group.name)} · ${side} ${kind}`
        : `${escapeHtml(group.name)}<br>${units.length} units · ${side} · ${kind}`;
      const details = expanded
        ? `<strong>${escapeHtml(unit.name || unit.type)}</strong><br>${escapeHtml(unit.type)}<br>${escapeHtml(group.name)}<br>${unit.lat.toFixed(5)}, ${unit.lon.toFixed(5)}`
        : `<strong>${escapeHtml(group.name)}</strong><br>${units.length} units<br>Zoom in to inspect individual units`;
      const marker = L.marker([unit.lat, unit.lon], {icon})
        .bindTooltip(title, {className: 'map-label'})
        .bindPopup(details)
        .addTo(situationLayers.forces);
      marker.on('click', event => {
        L.DomEvent.stopPropagation(event.originalEvent);
        selectedSituationGroup = group.name;
        renderSituationMission(snapshot);
      });
    });
  });
  renderSituationMission(snapshot);
}

function renderSituationMission(snapshot) {
  situationLayers.missions.clearLayers();
  if (!selectedSituationGroup) return;
  const group = (snapshot?.groups || []).find(item => item.name === selectedSituationGroup);
  const deployment = (overview?.deployments || []).find(item =>
    item.name === selectedSituationGroup || (item.names || []).includes(selectedSituationGroup));
  const waypoints = deployment?.waypoints || [];
  const lead = group?.units?.find(unit => Number.isFinite(unit.lat) && Number.isFinite(unit.lon));
  if (!lead || !waypoints.length) return;
  const route = [[lead.lat, lead.lon], ...waypoints.map(point => [point.lat, point.lon])];
  L.polyline(route, {color: '#f5d879', weight: 3, opacity: .9, dashArray: '8 7'})
    .addTo(situationLayers.missions);
  waypoints.forEach((point, index) => {
    L.circleMarker([point.lat, point.lon], {
      radius: 7, color: '#111614', weight: 2, fillColor: '#f5d879', fillOpacity: 1
    }).bindTooltip(escapeHtml(point.label || `Waypoint ${index + 1}`), {
      permanent: true, direction: 'top', className: 'map-label mission-label', offset: [0, -6]
    }).bindPopup(`<strong>${escapeHtml(group.name)}</strong><br>${escapeHtml(point.label || `Waypoint ${index + 1}`)}<br>${point.lat.toFixed(5)}, ${point.lon.toFixed(5)}`)
      .addTo(situationLayers.missions);
  });
}

function renderSituation() {
  initializeSituationMap();
  if (!situationMap) {
    document.getElementById('map-meta').textContent = 'Map library unavailable';
    return;
  }
  Object.values(situationLayers).forEach(layer => layer.clearLayers());
  const objectives = overview.scenario.objectives;
  const objectiveById = Object.fromEntries(objectives.map(item => [item.id, item]));
  const states = overview.campaign?.objectives || {};
  const colors = {blue: '#277bc0', red: '#b94040', neutral: '#7c827d'};
  situationBounds = [];
  objectives.forEach(objective => {
    const owner = states[objective.id]?.owner || objective.initial_owner || 'neutral';
    const point = [objective.lat, objective.lon];
    situationBounds.push(point);
    objective.connections.filter(id => objective.id < id).forEach(id => {
      const neighbor = objectiveById[id];
      if (neighbor) L.polyline([point, [neighbor.lat, neighbor.lon]], {
        color: '#26362f', weight: 4, opacity: .75, dashArray: '7 7'
      }).addTo(situationLayers.objectives);
    });
    L.circleMarker(point, {
      radius: 9, color: '#fff', weight: 2, fillColor: colors[owner], fillOpacity: 1
    }).bindTooltip(escapeHtml(objective.label), {
      permanent: true, direction: 'top', className: 'map-label objective-label', offset: [0, -7]
    }).bindPopup(`<strong>${escapeHtml(objective.label)}</strong><br>${owner} controlled<br>+${objective.income} income`)
      .addTo(situationLayers.objectives);
  });
  const snapshot = debugStatus?.snapshot;
  (snapshot?.airbases || []).forEach(base => {
    const side = base.coalition === 2 ? 'blue' : base.coalition === 1 ? 'red' : 'neutral';
    L.circleMarker([base.lat, base.lon], {
      radius: 4, color: colors[side], weight: 2, fillColor: '#fff', fillOpacity: .8
    }).bindTooltip(`${escapeHtml(base.name)} · ${side}`, {className: 'map-label'})
      .addTo(situationLayers.airbases);
  });
  (snapshot?.groups || []).forEach(group => (group.units || []).forEach(unit => {
    if (Number.isFinite(unit.lat) && Number.isFinite(unit.lon)) {
      situationBounds.push([unit.lat, unit.lon]);
    }
  }));
  renderSituationForces(snapshot);
  (snapshot?.statics || []).forEach(item => {
    const side = item.coalition === 2 ? 'blue' : item.coalition === 1 ? 'red' : 'neutral';
    L.circleMarker([item.lat, item.lon], {
      radius: 3, color: colors[side], weight: 1, fillColor: colors[side], fillOpacity: .8
    }).bindTooltip(`${escapeHtml(item.name)} · ${escapeHtml(item.type)}`, {className: 'map-label'})
      .addTo(situationLayers.statics);
  });
  if (!situationFitted) {
    fitSituationMap();
    situationFitted = true;
  }
  renderSituationStats();
}

function renderSituationStats() {
  const snapshot = debugStatus?.snapshot;
  const states = overview.campaign?.objectives || {};
  for (const [side, coalition] of [['blue', 2], ['red', 1]]) {
    const owned = overview.scenario.objectives.filter(objective =>
      (states[objective.id]?.owner || objective.initial_owner) === side);
    const groups = (snapshot?.groups || []).filter(group => group.coalition === coalition && group.units?.length);
    const kills = (snapshot?.kill_reports || []).filter(report => report.side === coalition).length;
    document.getElementById(`${side}-resources`).textContent = overview.campaign?.resources?.[side] ?? '--';
    document.getElementById(`${side}-objectives`).textContent = owned.length;
    document.getElementById(`${side}-income`).textContent = owned.reduce((total, objective) => total + objective.income, 0);
    document.getElementById(`${side}-groups`).textContent = groups.length;
    document.getElementById(`${side}-units`).textContent = groups.reduce((total, group) => total + group.units.length, 0);
    document.getElementById(`${side}-kills`).textContent = kills;
  }
  const time = snapshot ? `${Math.floor(snapshot.mission_time / 60)} min` : '--';
  document.getElementById('map-meta').textContent = `${debugStatus?.connected ? 'DCS live' : 'DCS offline'} · ${time}`;
}

function renderActions() {
  const list = document.getElementById('legal-actions');
  const actions = overview?.legal_actions?.[selectedSide] || [];
  const labels = Object.fromEntries((overview?.scenario.actions || []).map(item => [item.id, item.label]));
  list.innerHTML = actions.length ? actions.map(action => `<div class="action-row"><strong>${labels[action.action]}</strong><span>${action.target}</span><span>${action.cost} cr</span></div>`).join('') : '<div class="empty">Start a campaign to calculate legal actions.</div>';
}

function renderGenerals() {
  const reserve = overview.generals.reserve;
  const deployments = overview.deployments || [];
  for (const side of ['blue', 'red']) {
    const sideDeployments = deployments.filter(item => item.side === side);
    const accepted = sideDeployments.filter(item => ['accepted', 'active'].includes(item.status)).length;
    const failed = sideDeployments.filter(item => item.status === 'failed').length;
    const resources = overview.campaign?.resources?.[side] ?? '--';
    document.getElementById(`${side}-general-status`).textContent = overview.campaign
      ? `${resources} resources. ${accepted} deployments accepted${failed ? `, ${failed} failed` : ''}. Protected reserve: ${reserve}.`
      : `Starts with a garrison at every owned objective and protects ${reserve} resources.`;
  }
  const countdown = overview.generals.next_income_seconds;
  document.getElementById('general-economy').textContent =
    `Seeded symmetric policy · income every ${overview.generals.income_interval_seconds / 60} min` +
    (countdown === null ? ' · campaign not running' : ` · next income and decision in ${countdown}s`);
}

function render() {
  document.getElementById('scenario-name').textContent = overview.scenario.name;
  const running = Boolean(overview.campaign);
  document.getElementById('new-game').disabled = running;
  document.getElementById('new-game').textContent = running ? 'Campaign active' : 'Start new campaign';
  document.getElementById('start-copy').textContent = running
    ? 'The rules are initialized. DCS population and reconciliation are the next implementation step.'
    : 'No campaign is running. DCS may connect before or after the rules are initialized.';
  const connection = document.getElementById('connection');
  connection.textContent = overview.dcs.connected ? 'DCS connected' : 'DCS offline';
  connection.style.color = overview.dcs.connected ? 'var(--blue)' : 'var(--red)';
  renderSituation();
  renderActions();
  renderGenerals();
  document.getElementById('debug-output').textContent = JSON.stringify({overview, dcs: debugStatus}, null, 2);
}

async function refresh() {
  try {
    const [overviewResponse, statusResponse] = await Promise.all([
      fetch('/api/overview', {cache: 'no-store'}),
      fetch('/api/debug/status', {cache: 'no-store'})
    ]);
    overview = await overviewResponse.json();
    debugStatus = await statusResponse.json();
    updateDebugGroups();
    render();
  } catch (error) {
    document.getElementById('connection').textContent = 'Service unavailable';
  }
}

async function initialize() {
  activatePage(location.hash.slice(1) || 'start');
  try {
    const [groundResponse, airResponse] = await Promise.all([
      fetch('/api/catalog'), fetch('/api/air-catalog')
    ]);
    debugCatalogs = {ground: await groundResponse.json(), air: await airResponse.json()};
    updateDebugPresets();
  } catch (error) {
    document.getElementById('debug-feedback').textContent = `Catalog unavailable: ${error.message}`;
    document.getElementById('debug-feedback').className = 'error';
  }
  await refresh();
}

initialize();
setInterval(refresh, 5000);