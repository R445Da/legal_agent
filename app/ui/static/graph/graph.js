/*
 * The Obsidian-style graph of the archive vault.
 *
 * Obsidian is an Electron desktop app with no web build, so its graph view
 * cannot be embedded in a page. This draws the same *files* instead — the
 * notes under آرشیو/ and the [[wikilinks]] between them — so the picture here
 * and the picture in Obsidian are two renderings of one set of notes.
 *
 * Colour is the tag, shape is the record type, size is the degree. The force
 * model is a spring per link, short-range repulsion through a uniform grid
 * (O(n) per tick rather than O(n²), which is what lets the whole archive move
 * at once), and a weak pull toward a per-tag anchor — that anchor is what
 * turns tags into visible clusters instead of one even mesh.
 *
 * It speaks Streamlit's component protocol by hand: componentReady on load,
 * setFrameHeight for its size, setComponentValue when a node is clicked. That
 * is what lets a click navigate the app without reloading the page and losing
 * the session.
 */
(function () {
  "use strict";

  const TAU = Math.PI * 2;

  const S = {
    nodes: [], edges: [], byName: new Map(), tags: [],
    palette: {}, colours: new Map(), anchors: new Map(),
    hidden: new Set(), highlight: new Set(), query: "",
    tx: 0, ty: 0, scale: 1, alpha: 1,
    hover: null, dragging: null, panning: false, last: null,
    width: 800, height: 560, started: false, t0: Date.now(),
  };

  const canvas = document.getElementById("c");
  const ctx = canvas.getContext("2d");
  const tip = document.getElementById("tip");
  const legend = document.getElementById("legend");
  const search = document.getElementById("q");

  /* ----------------------------------------------------------------- *
   * Streamlit protocol
   * ----------------------------------------------------------------- */
  function post(type, extra) {
    window.parent.postMessage(Object.assign({ isStreamlitMessage: true, type }, extra), "*");
  }
  function setHeight(h) { post("streamlit:setFrameHeight", { height: h }); }
  function setValue(v) { post("streamlit:setComponentValue", { value: v, dataType: "json" }); }

  window.addEventListener("message", function (event) {
    if (!event.data || event.data.type !== "streamlit:render") return;
    apply(event.data.args || {});
  });

  /* ----------------------------------------------------------------- *
   * Colour: a tag always gets the same colour, across reloads and across
   * sessions, because it is hashed from the tag's own text rather than from
   * its position in a list that changes whenever the archive does.
   * ----------------------------------------------------------------- */
  const WHEEL = [
    "#0F4C3A", "#7C2D2D", "#A9812E", "#2C5F8A", "#6B3FA0", "#1F7A6B",
    "#B5651D", "#4A6B22", "#8A2F5C", "#37628C", "#8C6A1F", "#5C4B8A",
  ];

  function hash(text) {
    let h = 2166136261;
    for (let i = 0; i < text.length; i++) {
      h ^= text.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    return Math.abs(h);
  }

  function colourOf(node) {
    if (!node.tag) return S.palette.gray || "#6E6858";
    if (!S.colours.has(node.tag)) S.colours.set(node.tag, WHEEL[hash(node.tag) % WHEEL.length]);
    return S.colours.get(node.tag);
  }

  /* ----------------------------------------------------------------- *
   * Data
   * ----------------------------------------------------------------- */
  function apply(args) {
    S.palette = args.palette || {};
    S.highlight = new Set(args.highlight || []);
    const data = args.data || { nodes: [], edges: [], tags: [] };
    S.tags = data.tags || [];

    const previous = S.byName;
    S.nodes = (data.nodes || []).map(function (n) {
      const old = previous.get(n.name);
      const seed = hash(n.name);
      return Object.assign({}, n, {
        // Keep a node where it already was across a rerun, so a refresh does
        // not throw away a layout the user has been reading.
        x: old ? old.x : (seed % 1000) / 1000 * 600 - 300,
        y: old ? old.y : ((seed >> 10) % 1000) / 1000 * 400 - 200,
        vx: 0, vy: 0,
        r: Math.min(14, 4 + Math.sqrt(n.degree || 0) * 1.8),
      });
    });
    S.byName = new Map(S.nodes.map(function (n) { return [n.name, n]; }));

    S.edges = (data.edges || []).map(function (e) {
      return { source: S.byName.get(e.source), target: S.byName.get(e.target), caption: e.caption };
    }).filter(function (e) { return e.source && e.target; });

    // Every tag gets a fixed anchor on a circle; that is the cluster's centre.
    S.anchors.clear();
    const tags = S.tags.map(function (t) { return t.tag; });
    const radius = Math.min(S.width, S.height) * 0.34 + tags.length * 6;
    tags.forEach(function (tag, i) {
      const angle = (i / Math.max(1, tags.length)) * TAU;
      S.anchors.set(tag, { x: Math.cos(angle) * radius, y: Math.sin(angle) * radius });
    });

    drawLegend();
    S.alpha = 1;
    resize();
    if (!S.started) { S.started = true; tick(); }
  }

  function drawLegend() {
    legend.innerHTML = "";
    S.tags.slice(0, 14).forEach(function (t) {
      const chip = document.createElement("span");
      chip.className = "chip" + (S.hidden.has(t.tag) ? " off" : "");
      chip.style.background = S.palette.surface || "#fff";
      chip.style.color = S.palette.ink || "#142236";
      chip.style.borderColor = S.palette.line || "#E1DAC7";
      const name = t.tag.split("/").slice(-1)[0];
      chip.innerHTML = '<span class="dot" style="background:' +
        (S.colours.get(t.tag) || WHEEL[hash(t.tag) % WHEEL.length]) + '"></span>' + name;
      chip.onclick = function () {
        if (S.hidden.has(t.tag)) S.hidden.delete(t.tag); else S.hidden.add(t.tag);
        S.alpha = Math.max(S.alpha, 0.3);
        drawLegend();
      };
      legend.appendChild(chip);
    });
  }

  function visible(node) { return !(node.tag && S.hidden.has(node.tag)); }

  /* ----------------------------------------------------------------- *
   * Simulation
   * ----------------------------------------------------------------- */
  const LINK_LENGTH = 62;
  const CELL = 70;

  function step() {
    const nodes = S.nodes;
    if (!nodes.length) return;

    // Short-range repulsion. Every node lands in a grid cell and only looks at
    // the nine cells around it — at a few thousand notes the all-pairs version
    // would drop the frame rate through the floor for forces that are
    // negligible at that distance anyway.
    const grid = new Map();
    for (const n of nodes) {
      if (!visible(n)) continue;
      const key = Math.round(n.x / CELL) + "," + Math.round(n.y / CELL);
      if (!grid.has(key)) grid.set(key, []);
      grid.get(key).push(n);
    }
    for (const n of nodes) {
      if (!visible(n)) continue;
      const cx = Math.round(n.x / CELL), cy = Math.round(n.y / CELL);
      for (let i = -1; i <= 1; i++) {
        for (let j = -1; j <= 1; j++) {
          const bucket = grid.get((cx + i) + "," + (cy + j));
          if (!bucket) continue;
          for (const m of bucket) {
            if (m === n) continue;
            let dx = n.x - m.x, dy = n.y - m.y;
            let d2 = dx * dx + dy * dy;
            if (d2 > CELL * CELL * 2 || d2 === 0) continue;
            const d = Math.sqrt(d2) || 0.01;
            const force = (260 * (n.r + m.r) / 12) / d2;
            n.vx += (dx / d) * force;
            n.vy += (dy / d) * force;
          }
        }
      }
    }

    for (const e of S.edges) {
      if (!visible(e.source) || !visible(e.target)) continue;
      const dx = e.target.x - e.source.x, dy = e.target.y - e.source.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 0.01;
      const force = (d - LINK_LENGTH) * 0.018;
      const ux = (dx / d) * force, uy = (dy / d) * force;
      e.source.vx += ux; e.source.vy += uy;
      e.target.vx -= ux; e.target.vy -= uy;
    }

    for (const n of nodes) {
      if (!visible(n)) continue;
      const anchor = n.tag ? S.anchors.get(n.tag) : null;
      if (anchor) {
        n.vx += (anchor.x - n.x) * 0.0055;
        n.vy += (anchor.y - n.y) * 0.0055;
      } else {
        n.vx += -n.x * 0.002;
        n.vy += -n.y * 0.002;
      }
      if (n === S.dragging) continue;
      n.vx *= 0.86; n.vy *= 0.86;
      n.x += n.vx * S.alpha;
      n.y += n.vy * S.alpha;
    }

    S.alpha *= 0.994;
    if (S.alpha < 0.02) S.alpha = 0.02;
  }

  /* ----------------------------------------------------------------- *
   * Drawing
   * ----------------------------------------------------------------- */
  function shape(node, x, y, r) {
    ctx.beginPath();
    if (node.kind === "law") {
      ctx.rect(x - r, y - r, r * 2, r * 2);
    } else if (node.kind === "person") {
      ctx.moveTo(x, y - r); ctx.lineTo(x + r, y); ctx.lineTo(x, y + r); ctx.lineTo(x - r, y);
      ctx.closePath();
    } else if (node.kind === "org") {
      for (let i = 0; i < 6; i++) {
        const a = (i / 6) * TAU - Math.PI / 2;
        const px = x + Math.cos(a) * r, py = y + Math.sin(a) * r;
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      }
      ctx.closePath();
    } else {
      ctx.arc(x, y, r, 0, TAU);
    }
  }

  function neighbours(node) {
    const set = new Set([node.name]);
    for (const e of S.edges) {
      if (e.source === node) set.add(e.target.name);
      else if (e.target === node) set.add(e.source.name);
    }
    return set;
  }

  function matches(node) {
    return S.query && node.name.toLowerCase().indexOf(S.query) !== -1;
  }

  function draw() {
    const dpr = window.devicePixelRatio || 1;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, S.width, S.height);
    ctx.fillStyle = S.palette.paper || "#F3F0E7";
    ctx.fillRect(0, 0, S.width, S.height);

    ctx.save();
    ctx.translate(S.width / 2 + S.tx, S.height / 2 + S.ty);
    ctx.scale(S.scale, S.scale);

    const near = S.hover ? neighbours(S.hover) : null;
    const dim = function (node) {
      if (near && !near.has(node.name)) return 0.12;
      if (S.query && !matches(node)) return 0.15;
      return 1;
    };

    // Cluster titles sit behind everything, the way Obsidian labels a group.
    ctx.textAlign = "center";
    ctx.font = "600 13px Vazirmatn, system-ui, sans-serif";
    S.anchors.forEach(function (anchor, tag) {
      if (S.hidden.has(tag)) return;
      ctx.globalAlpha = 0.22;
      ctx.fillStyle = S.colours.get(tag) || "#6E6858";
      ctx.fillText(tag.split("/").slice(-1)[0], anchor.x, anchor.y);
    });

    ctx.lineWidth = 1 / S.scale;
    for (const e of S.edges) {
      if (!visible(e.source) || !visible(e.target)) continue;
      const alpha = Math.min(dim(e.source), dim(e.target));
      ctx.globalAlpha = alpha * 0.45;
      ctx.strokeStyle = S.palette.line || "#E1DAC7";
      if (near && near.has(e.source.name) && near.has(e.target.name)) {
        ctx.globalAlpha = 0.9;
        ctx.strokeStyle = S.palette.teal || "#0F4C3A";
      }
      ctx.beginPath();
      ctx.moveTo(e.source.x, e.source.y);
      ctx.lineTo(e.target.x, e.target.y);
      ctx.stroke();
    }

    const pulse = 0.5 + 0.5 * Math.sin((Date.now() - S.t0) / 260);
    for (const n of S.nodes) {
      if (!visible(n)) continue;
      const alpha = dim(n);
      const colour = colourOf(n);

      // A node a tool just touched keeps a breathing ring, so the agent's work
      // is visible on the graph while the run is still going.
      if (S.highlight.has(n.name)) {
        ctx.globalAlpha = 0.25 + 0.5 * pulse;
        ctx.strokeStyle = S.palette.stampRed || "#7C2D2D";
        ctx.lineWidth = 2.5 / S.scale;
        shape(n, n.x, n.y, n.r + 5 + pulse * 3);
        ctx.stroke();
        ctx.lineWidth = 1 / S.scale;
      }

      ctx.globalAlpha = alpha;
      ctx.fillStyle = colour;
      shape(n, n.x, n.y, n.r);
      ctx.fill();

      if (n === S.hover || matches(n)) {
        ctx.strokeStyle = S.palette.ink || "#142236";
        ctx.lineWidth = 1.6 / S.scale;
        ctx.stroke();
        ctx.lineWidth = 1 / S.scale;
      }

      // Labels only once there is room for them, exactly as Obsidian does.
      if (S.scale > 0.85 || n === S.hover || n.r > 9) {
        ctx.globalAlpha = alpha * (S.scale > 0.85 ? 0.85 : 1);
        ctx.fillStyle = S.palette.ink || "#142236";
        ctx.font = (n === S.hover ? "600 " : "") + (11 / S.scale).toFixed(1) +
          "px Vazirmatn, system-ui, sans-serif";
        const label = n.name.length > 26 ? n.name.slice(0, 25) + "…" : n.name;
        ctx.fillText(label, n.x, n.y + n.r + 12 / S.scale);
      }
    }

    ctx.restore();
    ctx.globalAlpha = 1;
  }

  function tick() {
    step();
    draw();
    requestAnimationFrame(tick);
  }

  /* ----------------------------------------------------------------- *
   * Interaction
   * ----------------------------------------------------------------- */
  function toWorld(event) {
    const rect = canvas.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left - S.width / 2 - S.tx) / S.scale,
      y: (event.clientY - rect.top - S.height / 2 - S.ty) / S.scale,
    };
  }

  function pick(point) {
    let best = null, bestD = Infinity;
    for (const n of S.nodes) {
      if (!visible(n)) continue;
      const dx = n.x - point.x, dy = n.y - point.y;
      const d = dx * dx + dy * dy;
      const reach = (n.r + 6) * (n.r + 6);
      if (d < reach && d < bestD) { best = n; bestD = d; }
    }
    return best;
  }

  canvas.addEventListener("mousedown", function (event) {
    const point = toWorld(event);
    const node = pick(point);
    if (node) { S.dragging = node; S.alpha = Math.max(S.alpha, 0.5); }
    else { S.panning = true; canvas.classList.add("grabbing"); }
    S.last = { x: event.clientX, y: event.clientY };
    S.movedSincePress = false;
  });

  window.addEventListener("mousemove", function (event) {
    if (S.dragging) {
      const point = toWorld(event);
      S.dragging.x = point.x; S.dragging.y = point.y;
      S.dragging.vx = 0; S.dragging.vy = 0;
      S.movedSincePress = true;
      return;
    }
    if (S.panning && S.last) {
      S.tx += event.clientX - S.last.x;
      S.ty += event.clientY - S.last.y;
      S.last = { x: event.clientX, y: event.clientY };
      S.movedSincePress = true;
      return;
    }
    const rect = canvas.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right ||
        event.clientY < rect.top || event.clientY > rect.bottom) {
      S.hover = null; tip.style.display = "none"; return;
    }
    const node = pick(toWorld(event));
    S.hover = node;
    if (node) {
      tip.style.display = "block";
      tip.style.background = S.palette.surface || "#fff";
      tip.style.color = S.palette.ink || "#142236";
      tip.style.border = "1px solid " + (S.palette.line || "#E1DAC7");
      const tagLine = node.tag ? '<div style="opacity:.7">' + node.tag + "</div>" : "";
      tip.innerHTML = "<b>" + node.name + "</b>" + tagLine +
        '<div style="opacity:.7">' + (node.degree || 0) + " پیوند</div>";
      const left = Math.min(event.clientX - rect.left + 14, S.width - 270);
      tip.style.left = Math.max(6, left) + "px";
      tip.style.top = (event.clientY - rect.top + 14) + "px";
    } else {
      tip.style.display = "none";
    }
  });

  window.addEventListener("mouseup", function (event) {
    // A click is a press that did not turn into a drag — otherwise dragging a
    // node across the canvas would also navigate away from the graph.
    if (S.dragging && !S.movedSincePress) {
      setValue({ node: S.dragging.name, at: Date.now() });
    } else if (S.dragging) {
      S.alpha = Math.max(S.alpha, 0.35);
    }
    S.dragging = null;
    S.panning = false;
    S.last = null;
    canvas.classList.remove("grabbing");
  });

  canvas.addEventListener("wheel", function (event) {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const mx = event.clientX - rect.left - S.width / 2;
    const my = event.clientY - rect.top - S.height / 2;
    const factor = Math.exp(-event.deltaY * 0.0014);
    const next = Math.max(0.15, Math.min(5, S.scale * factor));
    // Zoom toward the pointer rather than the centre, so the node under the
    // cursor stays under the cursor.
    S.tx = mx - (mx - S.tx) * (next / S.scale);
    S.ty = my - (my - S.ty) * (next / S.scale);
    S.scale = next;
  }, { passive: false });

  canvas.addEventListener("dblclick", function (event) {
    const node = pick(toWorld(event));
    if (node && node.uri) window.open(node.uri, "_blank");
  });

  search.addEventListener("input", function () {
    S.query = search.value.trim().toLowerCase();
    S.alpha = Math.max(S.alpha, 0.15);
  });

  function resize() {
    const dpr = window.devicePixelRatio || 1;
    S.width = document.getElementById("wrap").clientWidth || 800;
    S.height = 560;
    canvas.width = S.width * dpr;
    canvas.height = S.height * dpr;
    canvas.style.height = S.height + "px";
    search.style.background = S.palette.surface || "#fff";
    search.style.color = S.palette.ink || "#142236";
    search.style.border = "1px solid " + (S.palette.line || "#E1DAC7");
    setHeight(S.height + 4);
  }

  window.addEventListener("resize", resize);

  post("streamlit:componentReady", { apiVersion: 1 });
  setHeight(564);
})();
