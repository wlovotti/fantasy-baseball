/* Fantasy Baseball Draft Tracker — Frontend Logic */

const searchInput = document.getElementById("player-search");
const autocompleteList = document.getElementById("autocomplete-list");
const draftForm = document.getElementById("draft-form");
const undoBtn = document.getElementById("undo-btn");
const tableFilter = document.getElementById("table-filter");
const typeFilter = document.getElementById("type-filter");

let allPlayers = [];
let currentState = null;
let selectedIndex = -1;
let debounceTimer = null;

/* --- Autocomplete --- */

searchInput.addEventListener("input", () => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => fetchAutocomplete(searchInput.value), 150);
});

searchInput.addEventListener("keydown", (e) => {
  const items = autocompleteList.querySelectorAll(".autocomplete-item");
  if (e.key === "ArrowDown") {
    e.preventDefault();
    selectedIndex = Math.min(selectedIndex + 1, items.length - 1);
    highlightItem(items);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    selectedIndex = Math.max(selectedIndex - 1, 0);
    highlightItem(items);
  } else if (e.key === "Enter" && selectedIndex >= 0) {
    e.preventDefault();
    items[selectedIndex]?.click();
  } else if (e.key === "Escape") {
    closeAutocomplete();
  }
});

document.addEventListener("click", (e) => {
  if (!e.target.closest(".autocomplete-wrapper")) closeAutocomplete();
});

async function fetchAutocomplete(query) {
  if (query.length < 1) {
    closeAutocomplete();
    return;
  }
  const res = await fetch(`/api/players?q=${encodeURIComponent(query)}&limit=15`);
  const players = await res.json();
  renderAutocomplete(players, query);
}

function renderAutocomplete(players, query) {
  autocompleteList.innerHTML = "";
  selectedIndex = -1;

  players.forEach((p) => {
    const div = document.createElement("div");
    div.className = "autocomplete-item";
    div.innerHTML = `
      <span>${p.name} <span class="pos">${p.positions.join(",")}</span></span>
      <span class="val">$${p.original_value.toFixed(0)}</span>
    `;
    div.addEventListener("click", () => {
      searchInput.value = p.name;
      closeAutocomplete();
      document.getElementById("price").focus();
    });
    autocompleteList.appendChild(div);
  });

  // Always show "+ Add player" as last item
  const addDiv = document.createElement("div");
  addDiv.className = "autocomplete-item add-player-option";
  addDiv.innerHTML = `<span>+ Add player</span><span class="val">not listed</span>`;
  addDiv.addEventListener("click", () => {
    closeAutocomplete();
    openAddPlayerModal(query || "");
  });
  autocompleteList.appendChild(addDiv);

  autocompleteList.classList.add("active");
}

function highlightItem(items) {
  items.forEach((el, i) => el.classList.toggle("selected", i === selectedIndex));
}

function closeAutocomplete() {
  autocompleteList.classList.remove("active");
  autocompleteList.innerHTML = "";
  selectedIndex = -1;
}

/* --- Draft Form --- */

draftForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const playerName = searchInput.value.trim();
  const price = parseInt(document.getElementById("price").value);
  const teamId = parseInt(document.getElementById("team-select").value);

  if (!playerName) return;

  try {
    const res = await fetch("/api/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_name: playerName, price, team_id: teamId }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Draft failed");
      return;
    }
    const state = await res.json();
    updateUI(state);
    searchInput.value = "";
    document.getElementById("price").value = "1";
    searchInput.focus();
  } catch (err) {
    alert("Error: " + err.message);
  }
});

/* --- Undo --- */

undoBtn.addEventListener("click", async () => {
  try {
    const res = await fetch("/api/undo", { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Undo failed");
      return;
    }
    const state = await res.json();
    updateUI(state);
  } catch (err) {
    alert("Error: " + err.message);
  }
});

/* --- UI Updates --- */

function updateUI(state) {
  currentState = state;

  // Header stats
  document.getElementById("picks-remaining").textContent = state.picks_remaining;
  document.getElementById("picks-made").textContent = state.picks_made;

  // Player table
  allPlayers = state.top_players;
  renderPlayerTable();

  // Team budgets
  renderTeamBudgets(state.teams);

  // Position slots
  if (state.position_slots) renderPositionSlots(state.position_slots);

  // Tier depletion
  if (state.tier_counts) renderTierDepletion(state.tier_counts);

  // Recent picks
  renderRecentPicks(state.recent_picks);
}

function renderPlayerTable() {
  const filter = tableFilter.value.toLowerCase();
  const typeVal = typeFilter.value;
  const tbody = document.getElementById("player-tbody");

  const filtered = allPlayers.filter((p) => {
    if (filter && !p.name.toLowerCase().includes(filter)) return false;
    if (typeVal && p.player_type !== typeVal) return false;
    return true;
  });

  tbody.innerHTML = filtered
    .map((p, i) => {
      return `<tr>
        <td>${i + 1}</td>
        <td>${p.name}</td>
        <td>${p.positions.join(",")}</td>
        <td>${p.team}</td>
        <td>${p.points}</td>
        <td>$${p.original_value.toFixed(0)}</td>
      </tr>`;
    })
    .join("");
}

function renderTeamBudgets(teams) {
  const container = document.getElementById("team-budget-list");
  const entries = Object.entries(teams).sort((a, b) => a[0] - b[0]);
  container.innerHTML = `
    <div class="team-budget-header">
      <span>Team</span>
      <span>Budget / Roster / Max / Value</span>
    </div>` +
    entries
    .map(
      ([tid, t]) => {
        const isMyTeam = parseInt(tid) === MY_TEAM_ID;
        const cls = isMyTeam ? "team-budget-row my-team" : "team-budget-row";
        return `
    <div class="${cls}">
      <span class="team-name-link" onclick="openTeamRoster(${tid})">${t.name}</span>
      <span>
        <span class="budget">$${t.remaining_budget}</span>
        <span class="roster-count">(${t.roster_size}/24)</span>
        <span class="text-muted">max $${t.max_bid}</span>
        <span class="projected-value">val $${t.projected_value}</span>
      </span>
    </div>`;
      }
    )
    .join("");
}

function renderRecentPicks(picks) {
  const container = document.getElementById("recent-picks-list");
  if (!picks || picks.length === 0) {
    container.innerHTML = '<div class="pick-row">No picks yet</div>';
    return;
  }
  container.innerHTML = picks
    .map(
      (p) => `
    <div class="pick-row">
      <span>#${p.pick_number} ${p.player_name} → ${p.team_name}</span>
      <span class="pick-price">$${p.price}</span>
    </div>`
    )
    .join("");
}

/* --- Tier Depletion --- */

function renderTierDepletion(tierCounts) {
  const container = document.getElementById("tier-depletion-grid");
  const tiers = tierCounts.tiers;
  const positions = tierCounts.positions;

  let html = '<table class="tier-table"><thead><tr><th>Pos</th>';
  tiers.forEach((t) => { html += `<th>${t}</th>`; });
  html += "</tr></thead><tbody>";

  Object.keys(positions).forEach((pos) => {
    html += `<tr><td class="tier-pos">${pos}</td>`;
    positions[pos].forEach((count) => {
      const cls = count === 0 ? "depleted" : count <= 2 ? "scarce" : "";
      html += `<td class="${cls}">${count}</td>`;
    });
    html += "</tr>";
  });

  html += "</tbody></table>";
  container.innerHTML = html;
}

function toggleTiers() {
  const grid = document.getElementById("tier-depletion-grid");
  const icon = document.getElementById("tier-toggle-icon");
  if (grid.style.display === "none") {
    grid.style.display = "block";
    icon.textContent = "▼";
  } else {
    grid.style.display = "none";
    icon.textContent = "▶";
  }
}

/* --- Position Slots --- */

function renderPositionSlots(posSlots) {
  const container = document.getElementById("position-slots-grid");
  const labels = posSlots.labels;
  const teamsData = posSlots.teams;
  const opponentsTotal = posSlots.opponents_total;

  let html = '<table class="tier-table pos-slots-table"><thead><tr><th>Team</th>';
  labels.forEach((l) => { html += `<th>${l}</th>`; });
  html += "</tr></thead><tbody>";

  // Sort teams by ID
  const sortedTeamIds = Object.keys(teamsData).sort((a, b) => parseInt(a) - parseInt(b));

  for (const tid of sortedTeamIds) {
    const slots = teamsData[tid];
    const isMyTeam = parseInt(tid) === MY_TEAM_ID;
    const teamName = currentState && currentState.teams[tid] ? currentState.teams[tid].name : `Team ${tid}`;
    const rowCls = isMyTeam ? 'class="my-team"' : "";
    html += `<tr ${rowCls}><td class="tier-pos">${teamName}</td>`;
    labels.forEach((pos) => {
      const count = slots[pos] || 0;
      const cls = count === 0 ? "depleted" : count === 1 ? "scarce" : "";
      html += `<td class="${cls}">${count}</td>`;
    });
    html += "</tr>";
  }

  // Opponents total row
  html += `<tr class="opponents-row"><td class="tier-pos">Opponents</td>`;
  labels.forEach((pos) => {
    html += `<td>${opponentsTotal[pos] || 0}</td>`;
  });
  html += "</tr>";

  html += "</tbody></table>";
  container.innerHTML = html;
}

function togglePositionSlots() {
  const grid = document.getElementById("position-slots-grid");
  const icon = document.getElementById("pos-slots-toggle-icon");
  if (grid.style.display === "none") {
    grid.style.display = "block";
    icon.textContent = "▼";
  } else {
    grid.style.display = "none";
    icon.textContent = "▶";
  }
}

/* --- Team Roster Modal --- */

async function openTeamRoster(teamId) {
  try {
    const res = await fetch(`/api/team/${teamId}`);
    if (!res.ok) return;
    const data = await res.json();
    renderTeamRosterModal(data);
    document.getElementById("team-roster-modal").style.display = "flex";
  } catch (err) {
    alert("Error loading roster: " + err.message);
  }
}

function renderTeamRosterModal(data) {
  const body = document.getElementById("team-roster-body");
  let html = `
    <h2>${data.name}</h2>
    <div class="modal-stats">
      <span>Budget: <strong>$${data.remaining_budget}</strong></span>
      <span>Max Bid: <strong>$${data.max_bid}</strong></span>
      <span>Roster: <strong>${data.roster_size}/${data.max_roster}</strong></span>
      <span>Projected Value: <strong>$${data.projected_value}</strong></span>
    </div>
  `;

  if (data.roster.length === 0) {
    html += '<p class="text-muted">No players drafted yet.</p>';
  } else {
    html += `<table class="roster-table">
      <thead><tr>
        <th>Pos</th><th>Player</th><th>Price</th><th>Model $</th><th>Actions</th>
      </tr></thead><tbody>`;
    for (const p of data.roster) {
      html += `<tr>
        <td>${p.assigned_position}</td>
        <td>${p.player_name}</td>
        <td>
          <span id="price-display-${p.pick_number}">$${p.price}</span>
          <input type="number" id="price-edit-${p.pick_number}" class="price-edit-input"
            value="${p.price}" min="0" style="display:none">
        </td>
        <td>$${p.model_value}</td>
        <td class="action-btns">
          <button class="btn btn-sm" onclick="toggleEditPrice(${p.pick_number})">Edit $</button>
          <button class="btn btn-sm btn-save" id="save-btn-${p.pick_number}"
            onclick="savePrice(${p.pick_number})" style="display:none">Save</button>
          <button class="btn btn-sm btn-danger" onclick="removePick(${p.pick_number})">Remove</button>
        </td>
      </tr>`;
    }
    html += "</tbody></table>";
  }
  body.innerHTML = html;
}

function closeTeamRosterModal() {
  document.getElementById("team-roster-modal").style.display = "none";
  // Refresh main state
  loadInitialState();
}

function toggleEditPrice(pickNumber) {
  const display = document.getElementById(`price-display-${pickNumber}`);
  const input = document.getElementById(`price-edit-${pickNumber}`);
  const saveBtn = document.getElementById(`save-btn-${pickNumber}`);
  const isEditing = input.style.display !== "none";

  if (isEditing) {
    display.style.display = "inline";
    input.style.display = "none";
    saveBtn.style.display = "none";
  } else {
    display.style.display = "none";
    input.style.display = "inline";
    saveBtn.style.display = "inline";
    input.focus();
  }
}

async function savePrice(pickNumber) {
  const input = document.getElementById(`price-edit-${pickNumber}`);
  const newPrice = parseInt(input.value);

  try {
    const res = await fetch(`/api/pick/${pickNumber}/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ price: newPrice }),
    });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Edit failed");
      return;
    }
    const state = await res.json();
    updateUI(state);
    // Re-open the modal to show updated data
    const teamId = findTeamForPick(pickNumber);
    if (teamId) openTeamRoster(teamId);
  } catch (err) {
    alert("Error: " + err.message);
  }
}

async function removePick(pickNumber) {
  if (!confirm("Remove this pick? The player will return to the available pool.")) return;

  try {
    const res = await fetch(`/api/pick/${pickNumber}/remove`, { method: "POST" });
    if (!res.ok) {
      const err = await res.json();
      alert(err.detail || "Remove failed");
      return;
    }
    const state = await res.json();
    updateUI(state);
    // Re-open the modal to show updated data
    const teamId = findTeamForPick(pickNumber);
    if (teamId) {
      openTeamRoster(teamId);
    } else {
      closeTeamRosterModal();
    }
  } catch (err) {
    alert("Error: " + err.message);
  }
}

function findTeamForPick(pickNumber) {
  if (!currentState) return null;
  for (const pick of (currentState.recent_picks || [])) {
    if (pick.pick_number === pickNumber) return pick.team_id;
  }
  // Search through all draft log — not available client-side,
  // so we close the modal and let the user re-open
  return null;
}

/* --- Add Player Modal --- */

function openAddPlayerModal(prefillName) {
  document.getElementById("add-player-name").value = prefillName || "";
  // Uncheck all positions
  document.querySelectorAll('input[name="add-pos"]').forEach((cb) => { cb.checked = false; });
  document.getElementById("add-player-price").value = "1";
  document.getElementById("add-player-modal").style.display = "flex";
  document.getElementById("add-player-name").focus();
}

function closeAddPlayerModal() {
  document.getElementById("add-player-modal").style.display = "none";
}

document.getElementById("add-player-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const name = document.getElementById("add-player-name").value.trim();
  const price = parseInt(document.getElementById("add-player-price").value);
  const teamId = parseInt(document.getElementById("add-player-team").value);

  const positions = [];
  document.querySelectorAll('input[name="add-pos"]:checked').forEach((cb) => {
    positions.push(cb.value);
  });

  if (!name) { alert("Please enter a player name."); return; }
  if (positions.length === 0) { alert("Please select at least one position."); return; }

  // Derive player type from positions
  const hittingPositions = ["C", "1B", "2B", "3B", "SS", "OF"];
  const isHitter = positions.some((p) => hittingPositions.includes(p));
  const playerType = isHitter ? "hitter" : "pitcher";

  try {
    // First add the player to the pool
    const addRes = await fetch("/api/player/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, positions, player_type: playerType }),
    });
    if (!addRes.ok) {
      const err = await addRes.json();
      alert(err.detail || "Add player failed");
      return;
    }

    // Then draft them
    const draftRes = await fetch("/api/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_name: name, price, team_id: teamId }),
    });
    if (!draftRes.ok) {
      const err = await draftRes.json();
      alert(err.detail || "Draft failed");
      return;
    }
    const state = await draftRes.json();
    updateUI(state);
    closeAddPlayerModal();
    searchInput.value = "";
    searchInput.focus();
  } catch (err) {
    alert("Error: " + err.message);
  }
});

/* --- Table Filtering --- */

tableFilter.addEventListener("input", renderPlayerTable);
typeFilter.addEventListener("change", renderPlayerTable);

/* --- Initial Load --- */

async function loadInitialState() {
  try {
    const res = await fetch("/api/state");
    const state = await res.json();
    updateUI(state);
  } catch (err) {
    console.error("Failed to load initial state:", err);
  }
}

loadInitialState();
