"use strict";
// Interface Pseudo-FEC. Aucune donnée n'est injectée via innerHTML (protection XSS).
const TOKEN = document.querySelector('meta[name="pf-token"]').content;
const main = document.getElementById("main");
const S = { state: null, dossier: null, view: "home", fecs: [] };

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (v === true) el.setAttribute(k, "");
    else if (v !== false && v != null) el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid.nodeType ? kid : document.createTextNode(kid));
  return el;
}

async function api(method, path, body, extraHeaders) {
  const opts = { method, headers: { "X-PF-Token": TOKEN, ...(extraHeaders || {}) } };
  if (body !== undefined) { opts.body = body instanceof File ? body : JSON.stringify(body); }
  const r = await fetch(path, opts);
  const data = await r.json().catch(() => ({ error: "Réponse illisible." }));
  if (!r.ok) throw new Error(data.error || "Erreur.");
  return data;
}

const put = (el, ...kids) => el.replaceChildren(...kids.flat().filter((k) => k != null && k !== false));
const msg = (cls, text) => h("div", { class: "msg " + cls, role: "alert" }, text);
const fmtN = (s) => Number(s).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const CLASSES = { tiers_commerciaux: "Tiers commerciaux (40x, 41x)", personnel: "Personnel (42x)",
  groupe_associes: "Groupe et associés (45x)", divers: "Divers (467)",
  participations_prets: "Participations et prêts (26x, 27x)", emprunts: "Emprunts (16x)" };
const fmtI = (n) => Number(n).toLocaleString("fr-FR");

// ------------------------------------------------------------------ navigation
const STEPS = [
  ["home", "1 · Accueil"], ["fiche", "2 · Fiche dossier"], ["fec", "3 · Import du FEC"],
  ["noms", "4 · Noms à valider"], ["pseudo", "5 · Pseudonymisation"],
  ["texte", "6 · Texte libre"], ["reid", "7 · Ré-identification"],
];
const AVAILABLE = new Set(["home", "fiche", "fec", "noms"]);

function renderSteps() {
  const nav = document.getElementById("steps");
  nav.replaceChildren(...STEPS.map(([id, label]) => {
    const usable = AVAILABLE.has(id) && (id === "home" || (S.state && S.state.dossier) || (id === "fiche" && S.dossier));
    return h("button", {
      class: "step" + (S.view === id ? " on" : "") + (usable ? "" : " dis"),
      disabled: !usable, title: AVAILABLE.has(id) ? "" : "Prochain jalon",
      onclick: () => go(id),
    }, label);
  }));
  document.getElementById("who").textContent = S.state && S.state.dossier ? "Dossier " + S.state.dossier : "";
  document.getElementById("btn-lock").hidden = !(S.state && S.state.unlocked);
}

async function refresh() { S.state = await api("GET", "/api/state"); }
async function go(view) { S.view = view; await render(); }

async function render() {
  renderSteps();
  main.replaceChildren();
  try {
    if (!S.state.unlocked) return renderLogin();
    if (S.view === "fiche" && S.dossier) return renderFiche();   // y compris un nouveau dossier pas encore créé
    if (S.view === "home" || !S.state.dossier) { S.view = "home"; renderSteps(); return await renderHome(); }
    if (S.view === "fec") return await renderFec();
    if (S.view === "noms") return await renderNoms();
  } catch (e) { main.append(msg("err", e.message)); }
}

// ------------------------------------------------------------------ connexion
function renderLogin() {
  const first = !S.state.canary;
  const pass = h("input", { type: "password", id: "pp", autocomplete: "off", autofocus: true });
  const conf = h("input", { type: "password", id: "pp2", autocomplete: "off" });
  const box = h("div");
  const submit = async () => {
    box.replaceChildren();
    try {
      S.state = await api("POST", "/api/unlock", { passphrase: pass.value, confirm: conf.value });
      pass.value = conf.value = "";
      await go("home");
    } catch (e) { box.append(msg("err", e.message)); }
  };
  [pass, conf].forEach((i) => i.addEventListener("keydown", (ev) => ev.key === "Enter" && submit()));
  main.append(
    h("h1", {}, first ? "Première utilisation : définir la phrase secrète du cabinet" : "Phrase secrète du cabinet"),
    h("p", { class: "muted" }, first
      ? "Elle chiffre les tables de correspondance. Elle n'est jamais enregistrée : en cas de perte, les tables sont irrécupérables. Conservez-la dans le coffre du cabinet."
      : "Saisissez la phrase secrète pour accéder aux dossiers. Attention aux majuscules et aux apostrophes."),
    h("div", { class: "card" },
      h("label", { for: "pp" }, "Phrase secrète"), pass,
      first && [h("label", { for: "pp2" }, "Confirmer la phrase secrète"), conf],
      box, h("div", { class: "actions" }, h("button", { onclick: submit }, "Déverrouiller"))));
}

// ------------------------------------------------------------------ accueil
async function renderHome() {
  const { dossiers } = await api("GET", "/api/dossiers");
  const code = h("input", { id: "code", placeholder: "ex. D2025-017 (code neutre, sans nom de client)", maxlength: 32 });
  const box = h("div");
  const open = async (c) => {
    try { S.dossier = await api("POST", "/api/dossier/open", { code: c }); await refresh(); await go("fec"); }
    catch (e) { box.replaceChildren(msg("err", e.message)); }
  };
  main.append(
    h("h1", {}, "Dossiers"),
    h("p", { class: "muted" }, "Une table chiffrée par dossier client. Tables : " + S.state.tables_root),
    h("div", { class: "list" }, dossiers.length
      ? dossiers.map((c) => h("div", { class: "item" }, h("strong", {}, c), h("button", { class: "small", onclick: () => open(c) }, "Ouvrir")))
      : h("p", { class: "muted" }, "Aucun dossier pour l'instant.")),
    box,
    h("h2", {}, "Nouveau dossier"),
    h("div", { class: "card" },
      h("label", { for: "code" }, "Code dossier"), code,
      h("p", { class: "muted" }, "Ce code sert de nom de dossier et figure dans les fichiers produits : n'y mettez pas le nom du client."),
      h("div", { class: "actions" }, h("button", { onclick: () => {
        S.dossier = { code: code.value.trim(), fiche: emptyFiche(), entities: [], isNew: true };
        S.view = "fiche"; render();
      } }, "Créer la fiche dossier"))));
}

const emptyFiche = () => ({ societe: { raison_sociale: "", nom_commercial: "", sigle: "", variantes: [], siren: "", sirets: [] }, personnes: [], liees: [] });

// ------------------------------------------------------------------ fiche dossier
function renderFiche() {
  const d = S.dossier, f = JSON.parse(JSON.stringify(d.fiche));
  const box = h("div");
  const txt = (label, get, set, area) => {
    const el = h(area ? "textarea" : "input", {}); el.value = get();
    el.addEventListener("input", () => set(el.value));
    return h("div", {}, h("label", {}, label), el);
  };
  const lines = (a) => (a || []).join("\n");
  const unlines = (s) => s.split("\n").map((x) => x.trim()).filter(Boolean);
  const people = h("div"), liees = h("div");

  const drawPeople = () => people.replaceChildren(...f.personnes.map((p, i) => h("div", { class: "sub" },
    h("div", { class: "row" },
      txt("Nom et prénom", () => p.nom, (v) => (p.nom = v)),
      h("div", {}, h("label", {}, "Rôle"), (() => {
        const s = h("select", {}, ...Object.entries(S.state.roles).map(([k, v]) => h("option", { value: k, selected: p.role === k }, v)));
        s.addEventListener("change", () => (p.role = s.value)); return s; })())),
    txt("Variantes d'écriture (une par ligne)", () => lines(p.variantes), (v) => (p.variantes = unlines(v)), true),
    h("button", { class: "ghost small", onclick: () => { f.personnes.splice(i, 1); drawPeople(); } }, "Retirer"))));
  const drawLiees = () => liees.replaceChildren(...f.liees.map((c, i) => h("div", { class: "sub" },
    h("div", { class: "row" },
      txt("Raison sociale", () => c.raison_sociale, (v) => (c.raison_sociale = v)),
      h("div", {}, h("label", {}, "Lien"), (() => {
        const s = h("select", {}, ...Object.entries(S.state.liens).map(([k, v]) => h("option", { value: k, selected: c.lien === k }, v)));
        s.addEventListener("change", () => (c.lien = s.value)); return s; })())),
    h("div", { class: "row" },
      txt("SIREN", () => c.siren || "", (v) => (c.siren = v)),
      txt("SIRET (un par ligne)", () => lines(c.sirets), (v) => (c.sirets = unlines(v)), true)),
    txt("Variantes d'écriture (une par ligne)", () => lines(c.variantes), (v) => (c.variantes = unlines(v)), true),
    h("button", { class: "ghost small", onclick: () => { f.liees.splice(i, 1); drawLiees(); } }, "Retirer"))));
  drawPeople(); drawLiees();

  const save = async () => {
    box.replaceChildren();
    try {
      const path = d.isNew ? "/api/dossier/create" : "/api/dossier/fiche";
      S.dossier = await api("POST", path, { code: d.code, fiche: f });
      await refresh();
      if (S.dossier.warnings && S.dossier.warnings.length) {
        box.append(...S.dossier.warnings.map((w) => msg("warn", w)));
      } else { await go("fec"); return; }
      renderSteps();
    } catch (e) { box.append(msg("err", e.message)); }
  };

  main.append(
    h("h1", {}, "Fiche dossier"),
    h("p", { class: "muted" }, "Ces noms seront automatiquement cochés « à pseudonymiser » et recherchés dans tous les champs texte du FEC. Ils ne sont stockés que dans la table chiffrée."),
    h("h2", {}, "Société (pseudonyme SOC-0001)"),
    h("div", { class: "card" },
      h("div", { class: "row" },
        txt("Raison sociale", () => f.societe.raison_sociale, (v) => (f.societe.raison_sociale = v)),
        txt("Nom commercial", () => f.societe.nom_commercial, (v) => (f.societe.nom_commercial = v))),
      h("div", { class: "row" },
        txt("Sigle", () => f.societe.sigle, (v) => (f.societe.sigle = v)),
        txt("SIREN (9 chiffres)", () => f.societe.siren, (v) => (f.societe.siren = v))),
      txt("SIRET (un par ligne)", () => lines(f.societe.sirets), (v) => (f.societe.sirets = unlines(v)), true),
      txt("Autres variantes d'écriture (une par ligne)", () => lines(f.societe.variantes), (v) => (f.societe.variantes = unlines(v)), true)),
    h("h2", {}, "Dirigeants et associés (ASS-0001…)"),
    h("div", { class: "card" }, people,
      h("button", { class: "ghost small", onclick: () => { f.personnes.push({ nom: "", role: "dirigeant", variantes: [] }); drawPeople(); } }, "+ Ajouter une personne")),
    h("h2", {}, "Sociétés liées (GRP-0001…)"),
    h("div", { class: "card" }, liees,
      h("button", { class: "ghost small", onclick: () => { f.liees.push({ raison_sociale: "", lien: "autre", variantes: [], siren: "", sirets: [] }); drawLiees(); } }, "+ Ajouter une société liée")),
    box,
    h("div", { class: "actions" },
      h("button", { onclick: save }, d.isNew ? "Créer le dossier" : "Enregistrer la fiche"),
      h("button", { class: "ghost", onclick: () => go("home") }, "Retour")));
}

// ------------------------------------------------------------------ import FEC
async function renderFec() {
  S.fecs = (await api("GET", "/api/fec/list")).fecs;
  const box = h("div"), list = h("div");
  const input = h("input", { type: "file", multiple: true, accept: ".txt,.csv,.fec", hidden: true });
  const drop = h("div", { class: "drop" }, "Glissez ici un ou plusieurs FEC (un par exercice), ou ",
    h("a", { href: "#", onclick: (e) => { e.preventDefault(); input.click(); } }, "parcourez"),
    h("div", { class: "muted" }, "Maximum " + S.state.max_fec_mb + " Mo par fichier. Le fichier source n'est jamais modifié."));
  async function send(files) {
    box.replaceChildren();
    for (const file of files) {
      if (file.size > S.state.max_fec_mb * 1048576) { box.append(msg("err", "Fichier trop volumineux (maximum " + S.state.max_fec_mb + " Mo)."));; continue; }
      try {
        await api("POST", "/api/fec/upload", file, { "X-Filename": encodeURIComponent(file.name) });
      } catch (e) { box.append(msg("err", e.message)); }
    }
    S.fecs = (await api("GET", "/api/fec/list")).fecs; draw();
  }
  input.addEventListener("change", () => send([...input.files]));
  ["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", (e) => send([...e.dataTransfer.files]));

  const next = h("button", { onclick: () => go("noms") }, "Passer à la détection des noms");
  function draw() {
    list.replaceChildren(...S.fecs.map(card));
    next.disabled = !S.fecs.length || S.fecs.some((r) => r.bloquant);
  }
  function card(r) {
    const pill = r.bloquant ? h("span", { class: "pill err" }, "À corriger") : h("span", { class: "pill ok" }, "Contrôles passés");
    const lvl = { erreur: "err", avertissement: "warn", info: "ok" };
    const rows = [
      ["Lignes", fmtI(r.lignes)], ["Total débit", fmtN(r.total_debit)], ["Total crédit", fmtN(r.total_credit)],
      ["Équilibre", r.equilibre ? "oui" : "NON"], ["Comptes / auxiliaires", r.comptes + " / " + r.auxiliaires],
      ["Journaux", r.journaux], ["Exercice couvert", (r.exercice || "?") + (r.date_min ? "  (" + r.date_min + " → " + r.date_max + ")" : "")],
      ["SIREN du nom de fichier", r.siren_controle], ["Format", [r.separator, r.encoding, r.newline, "décimale : " + r.decimal].join(" · ")],
      ["Dates", Object.entries(r.formats_dates).map(([k, v]) => k + " " + v).join(" · ")],
    ];
    const cls = Object.entries(r.classes_tiers);
    return h("div", { class: "card" },
      h("div", { class: "item" }, h("div", {}, h("strong", {}, r.filename), " ", pill),
        h("button", { class: "ghost small", onclick: async () => { S.fecs = (await api("POST", "/api/fec/remove", { filename: r.filename })).fecs; draw(); } }, "Retirer")),
      h("table", {}, h("tbody", {}, rows.map(([k, v]) => h("tr", {}, h("th", {}, k), h("td", {}, v))))),
      r.issues.map((i) => msg(lvl[i.level], i.message)),
      cls.length && h("div", {},
        h("h2", {}, "Où figurent les noms de tiers ?"),
        h("table", {}, h("thead", {}, h("tr", {}, ["Classe de comptes", "Lignes", "Comptes", "Auxiliaires", "Nom porté par"].map((x) => h("th", {}, x)))),
          h("tbody", {}, cls.map(([k, v]) => h("tr", {}, h("td", {}, CLASSES[k] || k), h("td", { class: "num" }, fmtI(v.lignes)),
            h("td", { class: "num" }, v.comptes), h("td", { class: "num" }, v.auxiliaires), h("td", {}, v.mode)))))));
  }
  draw();
  main.append(
    h("h1", {}, "Import et contrôle du FEC"),
    h("p", { class: "muted" }, "Plusieurs exercices d'un même dossier peuvent être importés : ils partageront la même table de pseudonymes."),
    drop, input, box, list,
    h("div", { class: "actions" }, next),
    h("p", { class: "msg warn" }, "Étapes suivantes (pseudonymisation du FEC, texte libre, ré-identification) : prochains jalons."));
}

// ------------------------------------------------------------------ noms à valider
const CAT_ORDER = ["CLI", "FRN", "SAL", "ASS", "GRP", "TIE", "SOC"];
const SOURCES = { aux: "compte auxiliaire", compte: "libellé de compte", fiche: "fiche dossier", table: "table du dossier",
  libelle: "libellé d'écriture", manuel: "ajout manuel" };

function newRow(c) {
  return { key: c.key, uid: c.uid, nom: c.nom, cat: c.cat, checked: c.checked, defaultChecked: c.checked, source: c.source,
    confiance: c.confiance, statut: c.statut, liste_blanche: c.liste_blanche, pseudo: c.pseudo,
    variantes: c.variantes.map((v) => ({ ...v })), champs: c.champs, comptes: c.comptes, nb_comptes: c.nb_comptes,
    exemples: c.exemples, occurrences: c.occurrences, notes: c.notes, merge_with: c.merge_with,
    proposees: (c.variantes_proposees || []).map((v) => ({ ...v, coche: v.coche })),
    absorbed_uids: [], absorbed_keys: [], sel: false, touched: false, open: false };
}
function addVariant(t, v) {
  if (!v.texte || v.texte.toLowerCase() === t.nom.toLowerCase()) return;
  const ex = t.variantes.find((x) => x.texte.toLowerCase() === v.texte.toLowerCase());
  if (ex) ex.n += v.n; else t.variantes.push({ ...v });
}
function mergeRows(rows) {
  rows.sort((a, b) => (b.uid ? 1 : 0) - (a.uid ? 1 : 0) || ({ aux: 0, compte: 1 }[a.source] ?? 2) - ({ aux: 0, compte: 1 }[b.source] ?? 2) || b.occurrences - a.occurrences);
  const t = rows[0];
  for (const o of rows.slice(1)) {
    o.variantes.forEach((v) => addVariant(t, v));
    addVariant(t, { texte: o.nom, n: o.occurrences, origine: "fusion", risque: false, coche: true });
    o.proposees.forEach((v) => { if (!t.proposees.find((x) => x.texte === v.texte)) t.proposees.push(v); });
    t.occurrences += o.occurrences; t.exemples = [...t.exemples, ...o.exemples].slice(0, 3);
    t.checked = t.checked || o.checked; t.touched = true;
    if (o.uid) t.absorbed_uids.push(o.uid, ...o.absorbed_uids);
    t.absorbed_keys.push(o.key, ...o.absorbed_keys);
    t.notes = [...new Set([...t.notes, ...o.notes])];
  }
  S.rows = S.rows.filter((r) => !rows.slice(1).includes(r)); t.sel = false;
}
function mergeGroups() {  // composantes connexes du graphe des fusions proposées
  const byKey = new Map(); S.rows.forEach((r) => { byKey.set(r.key, r); r.absorbed_keys.forEach((k) => byKey.set(k, r)); });
  const seen = new Set(), groups = [];
  for (const r of S.rows) {
    if (seen.has(r)) continue;
    const comp = [], stack = [r];
    while (stack.length) {
      const x = stack.pop(); if (seen.has(x)) continue; seen.add(x); comp.push(x);
      [x.key, ...x.absorbed_keys].forEach(() => {});
      for (const k of x.merge_with) { const y = byKey.get(k); if (y && !seen.has(y)) stack.push(y); }
    }
    if (comp.length > 1) groups.push(comp);
  }
  return groups;
}

async function renderNoms() {
  const box = h("div"), body = h("div");
  const F = S.f = S.f || { q: "", cat: "", statut: "", conf: "", coche: "", weak: false, page: 0 };
  async function detect() {
    box.replaceChildren(h("p", { class: "muted" }, "Détection en cours…"));
    try { S.det = await api("POST", "/api/detect", {}); S.rows = S.det.candidats.map(newRow); box.replaceChildren(); draw(); }
    catch (e) { box.replaceChildren(msg("err", e.message)); }
  }
  const visible = () => S.rows.filter((r) => {
    if (!F.weak && r.confiance === "faible" && r.statut !== "connu" && !r.touched) return false;
    if (F.cat && r.cat !== F.cat) return false;
    if (F.statut && r.statut !== F.statut) return false;
    if (F.conf && r.confiance !== F.conf) return false;
    if (F.coche === "oui" && !r.checked) return false;
    if (F.coche === "non" && r.checked) return false;
    if (F.q) { const q = F.q.toLowerCase(); if (!r.nom.toLowerCase().includes(q) && !r.variantes.some((v) => v.texte.toLowerCase().includes(q))) return false; }
    return true;
  });
  const PAGE = 40;

  function rowView(r) {
    const chk = h("input", { type: "checkbox", checked: r.checked, "aria-label": "À pseudonymiser" });
    chk.addEventListener("change", () => { r.checked = chk.checked; r.touched = r.touched || r.checked !== r.defaultChecked; stats(); });
    const sel = h("input", { type: "checkbox", checked: r.sel, "aria-label": "Sélectionner" });
    sel.addEventListener("change", () => { r.sel = sel.checked; });
    const cat = h("select", { disabled: !!r.pseudo }, ...CAT_ORDER.filter((c) => c !== "SOC" || r.cat === "SOC").map((c) => h("option", { value: c, selected: r.cat === c }, c + " · " + S.state.categories[c])));
    cat.addEventListener("change", () => { r.cat = cat.value; r.touched = true; });
    const badges = [h("span", { class: "pill" }, SOURCES[r.source] || r.source),
      r.statut === "liste_blanche" && h("span", { class: "pill warn" }, "liste blanche"),
      r.statut === "connu" && h("span", { class: "pill ok" }, r.pseudo || "connu"),
      r.source === "libelle" && h("span", { class: "pill " + (r.confiance === "haute" ? "ok" : r.confiance === "moyenne" ? "warn" : "") }, "confiance " + r.confiance),
      r.merge_with.length > 0 && h("span", { class: "pill warn" }, "fusion proposée")];
    const det = h("div", { class: "ndetail" },
      r.variantes.length > 0 && h("div", {}, h("strong", {}, "Variantes d'écriture (cochées = recherchées partout) :"),
        r.variantes.map((v) => { const c = h("input", { type: "checkbox", checked: v.coche }); c.addEventListener("change", () => { v.coche = c.checked; r.touched = true; });
          return h("label", { class: "var" }, c, " ", v.texte, " ", h("span", { class: "muted" }, "(" + v.n + " · " + v.origine + (v.risque ? " · risque d'homonymie" : "") + ")")); })),
      r.proposees.length > 0 && h("div", {}, h("strong", {}, "Écritures possibles de ce nom (à cocher pour les inclure) :"),
        r.proposees.map((v) => { const c = h("input", { type: "checkbox", checked: v.coche }); c.addEventListener("change", () => {
            v.coche = c.checked; r.touched = true;
            if (c.checked) addVariant(r, { texte: v.texte, n: v.n, origine: "variante proposée", risque: v.risque, coche: true });
            else r.variantes = r.variantes.filter((x) => x.texte !== v.texte);
          });
          return h("label", { class: "var" }, c, " ", v.texte, " ", h("span", { class: "muted" }, "(" + v.n + (v.risque ? " · risque d'homonymie" : "") + ")")); })),
      r.exemples.length > 0 && h("div", {}, h("strong", {}, "Exemples (affichés en local uniquement) :"), r.exemples.map((x) => h("div", { class: "ex" }, x))),
      h("div", { class: "muted" }, "Champs : " + Object.entries(r.champs).map(([k, v]) => k + " " + v).join(", ") + (r.comptes.length ? " · Comptes : " + r.comptes.join(", ") + (r.nb_comptes > r.comptes.length ? "…" : "") : "")),
      r.notes.filter((n) => !n.startsWith("forme")).map((n) => h("div", { class: "msg warn" }, n)));
    const d = h("details", { open: r.open }, h("summary", {}, "Détails"), det);
    d.addEventListener("toggle", () => { r.open = d.open; });
    return h("div", { class: "nrow" + (r.checked ? " on" : "") },
      h("div", { class: "ncheck" }, chk, h("span", { class: "muted" }, "pseudo."), sel, h("span", { class: "muted" }, "fusion")),
      h("div", { class: "nmain" }, h("div", { class: "nname" }, r.nom), h("div", { class: "nbadges" }, badges), d),
      h("div", { class: "nside" }, cat, h("div", { class: "muted" }, fmtI(r.occurrences) + " occurrence(s)")));
  }

  function stats() {
    const n = S.rows.filter((r) => r.checked).length, weak = S.rows.filter((r) => r.confiance === "faible" && !r.touched && r.statut !== "connu").length;
    S.statEl.textContent = n + " à pseudonymiser sur " + S.rows.length + " propositions" + (weak && !F.weak ? " · " + weak + " propositions peu fiables masquées" : "");
  }

  function draw() {
    const vis = visible(), pages = Math.max(1, Math.ceil(vis.length / PAGE)); F.page = Math.min(F.page, pages - 1);
    const groups = mergeGroups();
    S.statEl = h("strong", { id: "stat" });
    const sel = (opts, key, label) => { const s = h("select", {}, ...opts.map(([v, t]) => h("option", { value: v, selected: F[key] === v }, t))); s.addEventListener("change", () => { F[key] = s.value; F.page = 0; draw(); }); return h("label", { class: "flt" }, label, s); };
    const q = h("input", { type: "search", placeholder: "Rechercher un nom ou une variante", value: F.q }); q.addEventListener("input", () => { F.q = q.value; F.page = 0; clearTimeout(S.tq); S.tq = setTimeout(draw, 250); });
    const wk = h("input", { type: "checkbox", checked: F.weak }); wk.addEventListener("change", () => { F.weak = wk.checked; F.page = 0; draw(); });
    const dr = S.det;
    const manNom = h("input", { placeholder: "Nom à ajouter (ex. Jean DUPONT)" }), manCat = h("select", {}, ...CAT_ORDER.filter((c) => c !== "SOC").map((c) => h("option", { value: c }, c + " · " + S.state.categories[c])));
    put(body,
      dr.conflits.length > 0 && h("div", { class: "msg err" }, h("strong", {}, "Conflits à résoudre avant pseudonymisation : "), "un même texte est rattaché à deux entités — ",
        dr.conflits.map((c) => "« " + c.texte + " » (" + c.entites.join(" / ") + ")").join(" ; "), ". Décochez une variante ou fusionnez les entités."),
      dr.sensibles.total > 0 && h("div", { class: "card" }, h("strong", {}, "Motifs sensibles détectés (remplacés par des jetons neutres, non réversibles) : "),
        h("table", {}, h("tbody", {}, dr.sensibles.types.map((t) => h("tr", {}, h("td", {}, t.type), h("td", { class: "num" }, fmtI(t.n)), h("td", {}, Object.keys(t.champs).join(", ")), h("td", {}, t.exemple), h("td", {}, "→ " + t.remplacement)))))),
      dr.incrustations.message && h("div", { class: "msg warn" }, dr.incrustations.message + " (CompAuxNum : " + dr.incrustations.CompAuxNum + ", CompteNum : " + dr.incrustations.CompteNum + ")"),
      groups.length > 0 && h("div", { class: "msg warn" }, groups.length + " regroupement(s) de variantes proposé(s) (même nom écrit différemment). ",
        h("button", { class: "small", onclick: () => { groups.forEach(mergeRows); draw(); } }, "Appliquer tous les regroupements"), " Vous pouvez aussi fusionner à la main."),
      h("div", { class: "card" }, S.statEl,
        h("div", { class: "filters" }, q, sel([["", "Toutes catégories"], ...CAT_ORDER.map((c) => [c, c])], "cat", ""), sel([["", "Tous statuts"], ["nouveau", "Nouveaux"], ["connu", "Connus"], ["liste_blanche", "Liste blanche"]], "statut", ""),
          sel([["", "Toute confiance"], ["haute", "Haute"], ["moyenne", "Moyenne"], ["faible", "Faible"]], "conf", ""), sel([["", "Cochés ou non"], ["oui", "Cochés"], ["non", "Non cochés"]], "coche", ""),
          h("label", { class: "flt" }, wk, " afficher les propositions peu fiables")),
        h("div", { class: "actions" },
          h("button", { class: "ghost small", onclick: () => { vis.forEach((r) => { r.checked = true; r.touched = r.touched || !r.defaultChecked; }); draw(); } }, "Cocher les " + vis.length + " affichés"),
          h("button", { class: "ghost small", onclick: () => { vis.forEach((r) => { r.checked = false; r.touched = r.touched || r.defaultChecked; }); draw(); } }, "Décocher les affichés"),
          h("button", { class: "ghost small", onclick: () => { const s = S.rows.filter((r) => r.sel); if (s.length < 2) return alert("Sélectionnez au moins deux lignes (colonne « fusion »)."); mergeRows(s); draw(); } }, "Fusionner la sélection"),
          h("button", { class: "ghost small", onclick: addWhitelist }, "Ajouter la sélection à la liste blanche"))),
      h("div", {}, vis.slice(F.page * PAGE, F.page * PAGE + PAGE).map(rowView)),
      h("div", { class: "actions" }, h("button", { class: "ghost small", disabled: F.page === 0, onclick: () => { F.page--; draw(); } }, "← Précédent"), h("span", { class: "muted" }, "Page " + (F.page + 1) + " / " + pages + " (" + vis.length + " lignes)"),
        h("button", { class: "ghost small", disabled: F.page >= pages - 1, onclick: () => { F.page++; draw(); } }, "Suivant →")),
      h("div", { class: "card" }, h("strong", {}, "Ajout manuel d'un nom"), h("div", { class: "row" }, manNom, manCat),
        h("div", { class: "actions" }, h("button", { class: "ghost small", onclick: () => {
          if (!manNom.value.trim()) return;
          S.rows.unshift(newRow({ key: manNom.value.trim().toLowerCase(), uid: null, nom: manNom.value.trim(), cat: manCat.value, checked: true, source: "manuel", confiance: "haute", statut: "nouveau", liste_blanche: null, pseudo: null, variantes: [], champs: {}, comptes: [], nb_comptes: 0, exemples: [], occurrences: 0, notes: [], merge_with: [] }));
          S.rows[0].touched = true; draw(); } }, "Ajouter"))),
      h("div", { class: "actions" }, h("button", { onclick: save }, "Enregistrer les décisions")));
    stats();
  }

  async function addWhitelist() {
    const sel = S.rows.filter((r) => r.sel); if (!sel.length) return alert("Sélectionnez des lignes (colonne « fusion »).");
    if (!confirm("Ajouter " + sel.length + " tiers à la liste blanche du CABINET ? Ils ne seront plus pseudonymisés par défaut dans tous les dossiers. L'ajout est tracé.")) return;
    for (const r of sel) { try { await api("POST", "/api/whitelist/add", { nom: r.nom }); r.statut = "liste_blanche"; r.checked = false; r.touched = true; r.sel = false; } catch (e) { box.append(msg("err", e.message)); } }
    draw();
  }
  async function save() {
    const rows = S.rows.filter((r) => r.checked || r.touched || ["aux", "compte", "fiche", "table", "manuel"].includes(r.source)).map((r) => ({
      uid: r.uid, nom: r.nom, cat: r.cat, checked: r.checked, source: r.source, touched: r.touched,
      variantes: r.variantes.filter((v) => v.coche).map((v) => v.texte), absorbed_uids: r.absorbed_uids }));
    box.replaceChildren();
    try {
      const out = await api("POST", "/api/entities/save", { rows });
      box.append(msg(out.bloquant ? "err" : "ok", out.a_pseudonymiser + " entité(s) à pseudonymiser enregistrée(s) dans la table chiffrée (" + out.created + " créée(s), " + out.updated + " mise(s) à jour)."));
      out.warnings.forEach((w) => box.append(msg("warn", w)));
      if (out.conflicts.length) box.append(msg("err", "Conflits : " + out.conflicts.map((c) => "« " + c.texte + " » (" + c.entites.join(" / ") + ")").join(" ; ")));
      await detectQuiet();
    } catch (e) { box.append(msg("err", e.message)); }
  }
  async function detectQuiet() { /* recharge l'état connu sans perdre les choix : pseudonymes attribués */
    const prev = new Map(S.rows.map((r) => [r.nom.toLowerCase(), r]));
    S.det = await api("POST", "/api/detect", {});
    const fresh = S.det.candidats.map(newRow);
    fresh.forEach((r) => { const o = prev.get(r.nom.toLowerCase()); if (o) { r.sel = false; r.open = o.open; } });
    S.rows = fresh; draw();
  }

  main.append(h("h1", {}, "Noms à valider"),
    h("p", { class: "muted" }, "Propositions de pseudonymisation issues du FEC et de la fiche dossier. Les propositions heuristiques tirées des libellés sont indicatives : vérifiez-les. Les tiers usuels (liste blanche) sont maintenus sauf si vous les cochez."),
    box, body);
  if (S.det && S.rows) draw(); else await detect();
}

// ------------------------------------------------------------------ boutons du haut
document.getElementById("btn-quit").addEventListener("click", async () => {
  try { await api("POST", "/api/quit", {}); } catch (_) {}
  document.body.replaceChildren(h("main", {}, h("h1", {}, "Application arrêtée"), h("p", { class: "muted" }, "Vous pouvez fermer cet onglet.")));
});
document.getElementById("btn-lock").addEventListener("click", async () => {
  S.state = await api("POST", "/api/lock", {}); S.dossier = null; await go("home");
});
setInterval(() => api("GET", "/api/ping").catch(() => {}), 15000);
refresh().then(render).catch((e) => main.append(msg("err", e.message)));
