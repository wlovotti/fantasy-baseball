/* Fantasy Baseball Draft Tracker — Frontend Logic */

const searchInput = document.getElementById("player-search");
const autocompleteList = document.getElementById("autocomplete-list");
const draftForm = document.getElementById("draft-form");
const undoBtn = document.getElementById("undo-btn");
const tableFilter = document.getElementById("table-filter");
const typeFilter = document.getElementById("type-filter");

let allPlayers = [];
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
  renderAutocomplete(players);
}

function renderAutocomplete(players) {
  autocompleteList.innerHTML = "";
  selectedIndex = -1;
  if (players.length === 0) {
    closeAutocomplete();
    return;
  }
  players.forEach((p) => {
    const div = document.createElement("div");
    div.className = "autocomplete-item";
    div.innerHTML = `
      <span>${p.name} <span class="pos">${p.positions.join(",")}</span></span>
      <span class="val">$${p.current_value.toFixed(0)}</span>
    `;
    div.addEventListener("click", () => {
      searchInput.value = p.name;
      closeAutocomplete();
      document.getElementById("price").focus();
    });
    autocompleteList.appendChild(div);
  });
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
  // Header stats
  document.getElementById("inflation-value").textContent = state.inflation_factor.toFixed(3);
  document.getElementById("players-remaining").textContent = state.players_remaining;
  document.getElementById("picks-made").textContent = state.picks_made;

  // Inflation color
  const inflEl = document.getElementById("inflation-value");
  if (state.inflation_factor > 1.05) inflEl.style.color = "#f44336";
  else if (state.inflation_factor < 0.95) inflEl.style.color = "#4caf50";
  else inflEl.style.color = "#00d2ff";

  // Player table
  allPlayers = state.top_players;
  renderPlayerTable();

  // Team budgets
  renderTeamBudgets(state.teams);

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
      const change = p.value_change;
      const changeClass =
        change > 0.5 ? "val-up" : change < -0.5 ? "val-down" : "val-neutral";
      const changeStr =
        change > 0 ? `+${change.toFixed(1)}` : change.toFixed(1);
      return `<tr>
        <td>${i + 1}</td>
        <td>${p.name}</td>
        <td>${p.positions.join(",")}</td>
        <td>${p.team}</td>
        <td>${p.points}</td>
        <td>$${p.original_value.toFixed(0)}</td>
        <td>$${p.current_value.toFixed(0)}</td>
        <td class="${changeClass}">${changeStr}</td>
      </tr>`;
    })
    .join("");
}

function renderTeamBudgets(teams) {
  const container = document.getElementById("team-budget-list");
  const entries = Object.entries(teams).sort((a, b) => a[0] - b[0]);
  container.innerHTML = entries
    .map(
      ([tid, t]) => `
    <div class="team-budget-row">
      <span>${t.name}</span>
      <span>
        <span class="budget">$${t.remaining_budget}</span>
        <span class="roster-count">(${t.roster_size}/24)</span>
        <span class="text-muted">max $${t.max_bid}</span>
      </span>
    </div>`
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
      <span>#${p.pick_number} ${p.player_name} → Team ${p.team_id}</span>
      <span class="pick-price">$${p.price}</span>
    </div>`
    )
    .join("");
}

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
