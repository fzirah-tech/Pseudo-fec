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
const AVAILABLE = new Set(["home", "fiche", "fec"]);

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

  function draw() { list.replaceChildren(...S.fecs.map(card)); }
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
    h("p", { class: "msg warn" }, "Étapes suivantes (détection des noms, pseudonymisation, ré-identification) : prochains jalons."));
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
