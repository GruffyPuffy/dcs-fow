let overview;
let selectedSide = 'blue';

document.querySelectorAll('.tab').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.tab,.page').forEach(element => element.classList.remove('active'));
  button.classList.add('active');
  document.querySelector(`.page[data-page="${button.dataset.page}"]`).classList.add('active');
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

function renderGraph() {
  const objectives = overview.scenario.objectives;
  const states = overview.campaign?.objectives || {};
  const width = 1000, height = 300, padding = 70;
  const lats = objectives.map(item => item.lat), lons = objectives.map(item => item.lon);
  const position = objective => ({
    x: padding + (objective.lon - Math.min(...lons)) / (Math.max(...lons) - Math.min(...lons)) * (width - padding * 2),
    y: height - padding - (objective.lat - Math.min(...lats)) / (Math.max(...lats) - Math.min(...lats)) * (height - padding * 2)
  });
  const byId = Object.fromEntries(objectives.map(item => [item.id, item]));
  const lines = [];
  objectives.forEach(item => item.connections.filter(id => item.id < id).forEach(id => {
    const from = position(item), to = position(byId[id]);
    lines.push(`<line class="graph-line" x1="${from.x}" y1="${from.y}" x2="${to.x}" y2="${to.y}"/>`);
  }));
  const nodes = objectives.map(item => {
    const point = position(item), owner = states[item.id]?.owner || item.initial_owner || 'neutral';
    return `<g class="graph-node ${owner}" transform="translate(${point.x} ${point.y})"><circle r="13"/><text y="34">${item.label}</text></g>`;
  });
  const svg = document.getElementById('campaign-graph');
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.innerHTML = lines.join('') + nodes.join('');
}

function renderActions() {
  const list = document.getElementById('legal-actions');
  const actions = overview?.legal_actions?.[selectedSide] || [];
  const labels = Object.fromEntries((overview?.scenario.actions || []).map(item => [item.id, item.label]));
  list.innerHTML = actions.length ? actions.map(action => `<div class="action-row"><strong>${labels[action.action]}</strong><span>${action.target}</span><span>${action.cost} cr</span></div>`).join('') : '<div class="empty">Start a campaign to calculate legal actions.</div>';
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
  const resources = overview.campaign?.resources || {blue: 0, red: 0};
  document.getElementById('resources').innerHTML = `<div class="resource blue"><span>Blue resources</span><strong>${resources.blue}</strong></div><div class="resource red"><span>Red resources</span><strong>${resources.red}</strong></div>`;
  document.getElementById('objective-key').innerHTML = '<span>● Blue controlled</span><span>● Red controlled</span><span>● Neutral</span>';
  renderGraph();
  renderActions();
  document.getElementById('debug-output').textContent = JSON.stringify(overview, null, 2);
}

async function refresh() {
  try {
    const response = await fetch('/api/overview', {cache: 'no-store'});
    overview = await response.json();
    render();
  } catch (error) {
    document.getElementById('connection').textContent = 'Service unavailable';
  }
}

refresh();
setInterval(refresh, 5000);