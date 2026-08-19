/* The settings page.
 *
 * Writes go through pywebview.api on *commit* — blur, Enter, slider release — never on every
 * keystroke. Each save is picked up by the running application's config watcher, so writing
 * per character would reload it per character.
 */

"use strict";

const state = {
  values: {},
  explicit: {},
  restartOnly: [],
  pendingRestart: new Set(),
};

/* --- tabs ---------------------------------------------------------------- */

function showTab(name) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("is-active", tab.dataset.tab === name);
  }
  for (const panel of document.querySelectorAll(".panel")) {
    panel.classList.toggle("is-active", panel.dataset.panel === name);
  }
  document.dispatchEvent(new CustomEvent("tabshown", { detail: { name } }));
}

document.getElementById("dock").addEventListener("click", (event) => {
  const tab = event.target.closest(".tab");
  if (tab) showTab(tab.dataset.tab);
});

/* --- status line --------------------------------------------------------- */

let statusTimer = null;

function say(message, kind = "") {
  const bar = document.getElementById("status");
  bar.textContent = message;
  bar.className = "status" + (kind ? ` is-${kind}` : "");
  clearTimeout(statusTimer);
  if (kind === "ok" && message) {
    statusTimer = setTimeout(() => {
      if (state.pendingRestart.size) showPendingRestart();
      else say("");
    }, 2500);
  }
}

function showPendingRestart() {
  const names = [...state.pendingRestart].join(", ");
  say(`Restart Ghostwriter for: ${names}`, "warn");
}

/* --- values -------------------------------------------------------------- */

function value(path) {
  return state.values[path];
}

function isExplicit(path) {
  return Boolean(state.explicit[path]);
}

async function commit(changes) {
  const result = await window.pywebview.api.set_many(changes);
  if (!result.ok) {
    say(result.error || "Could not save", "bad");
    return false;
  }
  if (!result.changed.length) return true;

  Object.assign(state.values, changes);
  for (const path of result.changed) state.explicit[path] = true;
  for (const path of result.restartRequired) state.pendingRestart.add(path);

  if (state.pendingRestart.size) showPendingRestart();
  else say("Saved", "ok");
  document.dispatchEvent(new CustomEvent("committed", { detail: { changes } }));
  return true;
}

async function refresh() {
  const data = await window.pywebview.api.reload();
  adopt(data);
  document.dispatchEvent(new CustomEvent("refreshed"));
}

function adopt(data) {
  state.values = data.values;
  state.explicit = data.explicit;
  state.restartOnly = data.restartOnly;
  document.getElementById("config-path").textContent = data.path;
}

/* --- external edits ------------------------------------------------------ */
/* The user may have config.toml open in an editor. Reflect their change rather than sitting on
 * a stale copy and overwriting it on the next commit. */

async function watchForExternalEdits() {
  try {
    if (await window.pywebview.api.external_change()) {
      await refresh();
      say("Reloaded — config.toml changed on disk", "warn");
    }
  } catch (error) {
    /* The window is closing, or the bridge is gone. Nothing useful to do. */
  }
}

/* --- boot ---------------------------------------------------------------- */

window.addEventListener("pywebviewready", async () => {
  adopt(await window.pywebview.api.load());
  setInterval(watchForExternalEdits, 1500);
  document.dispatchEvent(new CustomEvent("ready"));
});

window.gw = { state, value, isExplicit, commit, refresh, say, showTab };
