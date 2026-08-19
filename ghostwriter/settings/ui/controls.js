/* Reusable controls.
 *
 * Every one of these commits on a *settled* interaction — blur, Enter, slider release — never
 * on each keystroke or drag pixel. A save is what applies a setting, so writing continuously
 * would reload the running application continuously.
 */

"use strict";

const el = (tag, attrs = {}, ...children) => {
  const node = document.createElement(tag);
  for (const [key, val] of Object.entries(attrs)) {
    if (key === "class") node.className = val;
    else if (key === "html") node.innerHTML = val;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), val);
    else if (val !== null && val !== undefined) node.setAttribute(key, val);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
};

/* --- containers ---------------------------------------------------------- */

function card(...children) {
  return el("div", { class: "card" }, ...children);
}

function row(label, hint, control) {
  return el(
    "div",
    { class: "row" },
    el("div", { class: "row-text" },
      el("div", { class: "row-label" }, label),
      hint ? el("div", { class: "row-hint" }, hint) : null),
    el("div", { class: "row-control" }, control),
  );
}

function sectionTitle(text, hint) {
  return el("div", { class: "section" },
    el("div", { class: "section-title" }, text),
    hint ? el("div", { class: "section-hint" }, hint) : null);
}

function advanced(text) {
  return el("div", { class: "advanced" }, el("span", { class: "advanced-mark" }, "▸"), text);
}

/* --- toggle -------------------------------------------------------------- */

function toggle(path, onChange) {
  const node = el("button", {
    class: "toggle",
    type: "button",
    role: "switch",
    "aria-checked": String(Boolean(gw.value(path))),
  }, el("span", { class: "toggle-knob" }));

  const paint = () => node.setAttribute("aria-checked", String(Boolean(gw.value(path))));
  node.addEventListener("click", async () => {
    const next = !gw.value(path);
    if (await gw.commit({ [path]: next })) {
      paint();
      if (onChange) onChange(next);
    }
  });
  document.addEventListener("refreshed", paint);
  return node;
}

/* --- slider -------------------------------------------------------------- */

function slider(path, { min, max, step = 0.01, format = (v) => v.toFixed(2), ends, onChange }) {
  const readout = el("span", { class: "readout" }, format(Number(gw.value(path))));
  const input = el("input", {
    type: "range", class: "slider",
    min: String(min), max: String(max), step: String(step),
    value: String(gw.value(path)),
  });

  // Track shows live while dragging; only release writes.
  input.addEventListener("input", () => {
    readout.textContent = format(Number(input.value));
    if (onChange) onChange(Number(input.value), false);
  });
  const settle = async () => {
    const next = Number(input.value);
    if (next === Number(gw.value(path))) return;
    if (await gw.commit({ [path]: next })) {
      if (onChange) onChange(next, true);
    }
  };
  input.addEventListener("change", settle);

  document.addEventListener("refreshed", () => {
    input.value = String(gw.value(path));
    readout.textContent = format(Number(gw.value(path)));
  });

  return el("div", { class: "slider-wrap" },
    el("div", { class: "slider-head" }, readout),
    input,
    ends ? el("div", { class: "slider-ends" },
      el("span", {}, ends[0]), el("span", {}, ends[1])) : null);
}

/* --- text and number fields ---------------------------------------------- */

function field(path, { width = 150, type = "text", parse = (v) => v, validate, mono = true } = {}) {
  const input = el("input", {
    type: type === "number" ? "text" : type,   // keep our own parsing, not the browser's
    class: "field" + (mono ? " mono" : ""),
    value: String(gw.value(path) ?? ""),
    style: `min-width:${width}px`,
  });

  const revert = () => { input.value = String(gw.value(path) ?? ""); input.classList.remove("is-bad"); };

  const settle = async () => {
    const raw = input.value.trim();
    let next;
    try {
      next = parse(raw);
    } catch {
      input.classList.add("is-bad");
      gw.say("That value is not valid", "bad");
      return;
    }
    if (validate && !validate(next)) {
      input.classList.add("is-bad");
      gw.say("That value is not valid", "bad");
      return;
    }
    input.classList.remove("is-bad");
    if (next === gw.value(path)) return;
    if (!(await gw.commit({ [path]: next }))) revert();
  };

  input.addEventListener("blur", settle);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); input.blur(); }
    if (event.key === "Escape") { revert(); input.blur(); }
  });
  document.addEventListener("refreshed", revert);
  return input;
}

const numberField = (path, opts = {}) =>
  field(path, {
    width: 70,
    parse: (raw) => {
      const value = Number(raw);
      if (raw === "" || Number.isNaN(value)) throw new Error("not a number");
      return opts.integer ? Math.round(value) : value;
    },
    validate: (value) =>
      (opts.min === undefined || value >= opts.min) &&
      (opts.max === undefined || value <= opts.max),
    ...opts,
  });

/* --- select -------------------------------------------------------------- */

function select(path, options, onChange) {
  const node = el("select", { class: "select" },
    ...options.map(([value, label]) =>
      el("option", { value: String(value), selected: gw.value(path) === value ? "" : null }, label)));
  node.addEventListener("change", async () => {
    const chosen = options.find(([value]) => String(value) === node.value);
    if (await gw.commit({ [path]: chosen[0] }) && onChange) onChange(chosen[0]);
  });
  document.addEventListener("refreshed", () => { node.value = String(gw.value(path)); });
  return node;
}

/* --- segmented ----------------------------------------------------------- */

function segmented(path, options, onChange) {
  const wrap = el("div", { class: "segmented" });
  const paint = () => {
    for (const button of wrap.children) {
      button.classList.toggle("is-on", button.dataset.value === String(gw.value(path)));
    }
  };
  for (const [value, label] of options) {
    wrap.append(el("button", {
      type: "button", class: "segment", "data-value": String(value),
      onclick: async () => {
        if (await gw.commit({ [path]: value })) { paint(); if (onChange) onChange(value); }
      },
    }, label));
  }
  paint();
  document.addEventListener("refreshed", paint);
  return wrap;
}

/* --- chips (string arrays) ----------------------------------------------- */

function chips(path, { placeholder = "add" } = {}) {
  const wrap = el("div", { class: "chips" });

  const write = async (list) => {
    if (await gw.commit({ [path]: list })) paint();
  };

  const paint = () => {
    wrap.textContent = "";
    const list = gw.value(path) || [];
    list.forEach((item, index) => {
      wrap.append(el("span", { class: "chip" }, item,
        el("button", {
          type: "button", class: "chip-x", title: `Remove ${item}`,
          onclick: () => write(list.filter((_, i) => i !== index)),
        }, "✕")));
    });

    const input = el("input", { class: "chip-input", placeholder: `+ ${placeholder}` });
    input.addEventListener("keydown", (event) => {
      if (event.key !== "Enter") return;
      event.preventDefault();
      const text = input.value.trim();
      if (text && !list.includes(text)) write([...list, text]);
      else input.value = "";
    });
    wrap.append(input);
  };

  paint();
  document.addEventListener("refreshed", paint);
  return wrap;
}

/* --- colour -------------------------------------------------------------- */

const HEX = /^#[0-9a-fA-F]{6}$/;

function colour(path, { palette = [], onChange } = {}) {
  const swatch = el("span", { class: "swatch" });
  const input = field(path, {
    width: 110,
    validate: (value) => HEX.test(value),
    parse: (raw) => (raw.startsWith("#") ? raw.toLowerCase() : `#${raw.toLowerCase()}`),
  });

  const paint = () => {
    const value = gw.value(path);
    swatch.style.background = value;
    swatch.style.boxShadow = `0 0 14px ${value}80`;
    for (const dot of dots.children) {
      dot.classList.toggle("is-on", dot.dataset.colour === value);
    }
    if (onChange) onChange(value);
  };

  const dots = el("div", { class: "dots" },
    ...palette.map((hex) => el("button", {
      type: "button", class: "dot", "data-colour": hex, title: hex,
      style: `background:${hex}`,
      onclick: async () => {
        if (await gw.commit({ [path]: hex })) { input.value = hex; paint(); }
      },
    })));

  document.addEventListener("committed", paint);
  document.addEventListener("refreshed", paint);
  queueMicrotask(paint);

  return el("div", { class: "colour" },
    el("div", { class: "colour-head" }, swatch, input), dots);
}

/* --- key capture --------------------------------------------------------- */

/* Maps a DOM keydown onto the names ghostwriter/keys/codes.py understands. Side-specific
 * modifiers matter: "right ctrl" must not be recorded as a generic "ctrl". */
const NAMED = {
  Escape: "esc", " ": "space", ArrowUp: "up", ArrowDown: "down",
  ArrowLeft: "left", ArrowRight: "right", Enter: "enter", Tab: "tab",
  Backspace: "backspace", Delete: "delete", Home: "home", End: "end",
  PageUp: "page up", PageDown: "page down", CapsLock: "caps lock",
};

function keyName(event) {
  const side = event.location === 1 ? "left " : event.location === 2 ? "right " : "";
  if (event.key === "Control") return `${side || "left "}ctrl`;
  if (event.key === "Shift") return `${side || "left "}shift`;
  if (event.key === "Alt") return `${side || "left "}alt`;
  if (event.key === "Meta") return `${side || "left "}windows`;
  if (NAMED[event.key]) return NAMED[event.key];
  if (/^F\d{1,2}$/.test(event.key)) return event.key.toLowerCase();
  if (event.key.length === 1) return event.key.toLowerCase();
  return null;
}

function chordFrom(event) {
  const trigger = keyName(event);
  if (!trigger) return null;
  const bare = ["left ctrl", "right ctrl", "left shift", "right shift",
                "left alt", "right alt", "left windows", "right windows"];
  if (bare.includes(trigger)) return trigger;   // a modifier pressed on its own

  const parts = [];
  if (event.ctrlKey) parts.push("ctrl");
  if (event.shiftKey) parts.push("shift");
  if (event.altKey) parts.push("alt");
  if (event.metaKey) parts.push("windows");
  parts.push(trigger);
  return parts.join("+");
}

function keyCapture(path, { allowEmpty = false, note } = {}) {
  const button = el("button", { type: "button", class: "keycap" });
  let capturing = false;

  const paint = () => {
    const value = gw.value(path);
    button.classList.toggle("is-unset", !value);
    button.textContent = capturing ? "press a key…" : value || "click to set";
  };

  const stop = () => {
    capturing = false;
    button.classList.remove("is-capturing");
    document.removeEventListener("keydown", onKey, true);
    paint();
  };

  const onKey = async (event) => {
    event.preventDefault();
    event.stopPropagation();
    if (event.key === "Escape") { stop(); return; }        // abandon, keep the old binding
    const chord = chordFrom(event);
    if (!chord) return;
    document.removeEventListener("keydown", onKey, true);
    capturing = false;
    button.classList.remove("is-capturing");
    await gw.commit({ [path]: chord });
    paint();
  };

  button.addEventListener("click", () => {
    if (capturing) { stop(); return; }
    capturing = true;
    button.classList.add("is-capturing");
    paint();
    document.addEventListener("keydown", onKey, true);
  });
  button.addEventListener("blur", () => { if (capturing) stop(); });

  document.addEventListener("refreshed", paint);
  paint();

  const wrap = el("div", { class: "keycap-wrap" }, button);
  if (allowEmpty) {
    wrap.append(el("button", {
      type: "button", class: "linkish", title: "Unbind",
      onclick: async () => { await gw.commit({ [path]: "" }); paint(); },
    }, "clear"));
  }
  if (note) wrap.append(el("span", { class: "keycap-note" }, note));
  return wrap;
}

window.ui = {
  el, card, row, sectionTitle, advanced, toggle, slider, field, numberField,
  select, segmented, chips, colour, keyCapture, chordFrom, HEX,
};
