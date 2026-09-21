/* ============================================================
   Summit — front-end logic
   ============================================================ */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const api = async (url, opts = {}) => {
  const res = await fetch(url, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  return res.json();
};

const STEPS = [
  { key: 'welcome',  label: 'Base camp' },
  { key: 'groq',     label: 'Groq' },
  { key: 'buffer',   label: 'Buffer' },
  { key: 'channel',  label: 'Channel' },
  { key: 'niche',    label: 'Your niche' },
  { key: 'sources',  label: 'Sources' },
  { key: 'voice',    label: 'Your voice' },
  { key: 'schedule', label: 'Rhythm' },
  { key: 'summit',   label: 'Summit' },
];

let step = 0;
let state = {};
let chosenChannel = null;
const sources = { feeds: [], finnhub: false };
let draftKey = null;
let countdownTimer = null;

/* ---------------- toasts ---------------- */
function toast(msg, bad = false) {
  const el = document.createElement('div');
  el.className = 'toast' + (bad ? ' bad' : '');
  el.innerHTML = `<span>${bad ? '⚠️' : '✅'}</span><span>${msg}</span>`;
  $('#toasts').appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 400); }, 3400);
}

/* ---------------- confetti ---------------- */
const cvs = $('#confetti'), ctx = cvs.getContext('2d');
let bits = [];
function sizeCanvas() { cvs.width = innerWidth; cvs.height = innerHeight; }
sizeCanvas(); addEventListener('resize', sizeCanvas);
function confetti(x = innerWidth / 2, y = innerHeight / 2, n = 90) {
  const colors = ['#ff9f43', '#2fbf87', '#4a9fe0', '#ffd166', '#ef6b6b', '#8fe0be'];
  for (let i = 0; i < n; i++) {
    const a = Math.random() * Math.PI * 2, sp = 3 + Math.random() * 9;
    bits.push({
      x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp - 4,
      s: 5 + Math.random() * 7, c: colors[(Math.random() * colors.length) | 0],
      rot: Math.random() * 6.28, vr: (Math.random() - .5) * .35, life: 90 + Math.random() * 40,
    });
  }
  if (bits.length === n) requestAnimationFrame(drawBits);
}
function drawBits() {
  ctx.clearRect(0, 0, cvs.width, cvs.height);
  bits = bits.filter(b => b.life-- > 0);
  bits.forEach(b => {
    b.x += b.vx; b.y += b.vy; b.vy += .22; b.vx *= .99; b.rot += b.vr;
    ctx.save(); ctx.translate(b.x, b.y); ctx.rotate(b.rot);
    ctx.fillStyle = b.c; ctx.globalAlpha = Math.min(1, b.life / 35);
    ctx.fillRect(-b.s / 2, -b.s / 2, b.s, b.s * .6); ctx.restore();
  });
  if (bits.length) requestAnimationFrame(drawBits);
  else ctx.clearRect(0, 0, cvs.width, cvs.height);
}

/* ---------------- parallax ---------------- */
addEventListener('mousemove', e => {
  const dx = (e.clientX / innerWidth - .5), dy = (e.clientY / innerHeight - .5);
  $$('[data-depth]').forEach(el => {
    const d = parseFloat(el.dataset.depth);
    el.style.transform = `translate3d(${-dx * d * 46}px, ${-dy * d * 26}px, 0)`;
  });
});

/* ---------------- wizard ---------------- */
function buildTrail() {
  $('#trailList').innerHTML = STEPS.map((s, i) =>
    `<li data-i="${i}"><span class="pip"></span>${s.label}</li>`).join('');
}

function paintTrail() {
  $$('#trailList li').forEach((li, i) => {
    li.classList.toggle('done', i < step);
    li.classList.toggle('active', i === step);
  });
  const pct = Math.round((step / (STEPS.length - 1)) * 100);
  $('#wizFill').style.width = pct + '%';
  $('#wizPct').textContent = pct + '%';
  $('#trailFill').style.height = (step / (STEPS.length - 1)) * 100 + '%';
  const li = $(`#trailList li[data-i="${step}"]`);
  if (li) $('#hiker').style.top = (li.offsetTop + $('#trailList').offsetTop - 6) + 'px';
}

function showStep(n, dir = 1) {
  const cards = $$('.step-card');
  const cur = $('.step-card.on');
  if (cur) { cur.classList.remove('on'); if (dir > 0) cur.classList.add('out-left'); }
  step = Math.max(0, Math.min(STEPS.length - 1, n));
  const next = cards[step];
  next.classList.remove('out-left');
  requestAnimationFrame(() => next.classList.add('on'));
  paintTrail();
  if (STEPS[step].key === 'channel') loadChannels();
  if (STEPS[step].key === 'niche') initNiche();
  if (STEPS[step].key === 'sources') loadSources();
  if (STEPS[step].key === 'voice') loadVoice();
  if (STEPS[step].key === 'schedule') renderPreviewTimes();
  if (STEPS[step].key === 'summit') celebrateSummit();
}

function setVerdict(id, html, cls = '') {
  const el = $('#verdict-' + id);
  el.className = 'verdict ' + cls;
  el.innerHTML = html;
}

async function verify(service) {
  const inputs = { groq: '#groqKey', finnhub: '#finnhubKey', buffer: '#bufferKey' };
  const input = $(inputs[service]);
  const key = input.value.trim();
  const field = input.closest('.field');
  if (!key) { field.classList.add('bad'); setVerdict(service, 'Paste a key first.', 'bad'); return; }

  const btn = $(`[data-verify="${service}"]`);
  btn.disabled = true;
  const label = btn.textContent;
  btn.innerHTML = '<span class="spinner"></span> Checking…';
  setVerdict(service, '<span class="spinner"></span> Talking to the API…');

  const r = await api(`/api/verify/${service}`, { method: 'POST', body: { api_key: key } });

  btn.disabled = false; btn.textContent = label;
  field.classList.remove('ok', 'bad');
  if (r.ok) {
    field.classList.add('ok');
    setVerdict(service, '<span class="tick">✓</span> Connected — key works.', 'good');
    confetti(innerWidth / 2, innerHeight / 2, 40);
    if (service === 'buffer' && r.channels) window._channels = r.channels;
    if (service === 'finnhub') sources.finnhub = true;
    else setTimeout(() => showStep(step + 1), 750);
  } else {
    field.classList.add('bad');
    setVerdict(service, '✕ ' + esc(r.error || 'That key did not work.'), 'bad');
  }
}

/* ---------------- channels ---------------- */
async function loadChannels() {
  const box = $('#channels');
  box.innerHTML = '<div class="loading-row"><span class="spinner"></span> Looking for channels…</div>';
  const r = window._channels ? { ok: true, channels: window._channels } : await api('/api/buffer/channels');
  window._channels = null;
  if (!r.ok) { box.innerHTML = `<div class="loading-row">Couldn't load channels: ${esc(r.error)}</div>`; return; }
  if (!r.channels.length) {
    box.innerHTML = '<div class="loading-row">No channels connected in Buffer yet.</div>';
    return;
  }
  box.innerHTML = r.channels.map(c => `
    <button class="channel" data-id="${esc(c.id)}" data-name="${esc(c.name)}">
      <span class="av">${(c.name || '?')[0].toUpperCase()}</span>
      <span><b>${esc(c.name)}</b><i>${esc(c.service)}</i></span>
      <span class="check">✓</span>
    </button>`).join('');
  $$('.channel', box).forEach(b => b.onclick = () => {
    $$('.channel', box).forEach(x => x.classList.remove('sel'));
    b.classList.add('sel');
    chosenChannel = { id: b.dataset.id, name: b.dataset.name };
    $('#channelNext').disabled = false;
    setVerdict('channel', `<span class="tick">✓</span> Posting to ${esc(b.dataset.name)}.`, 'good');
  });
}

/* ---------------- voice ---------------- */
async function loadVoice() {
  const r = await api('/api/voice_examples');
  const ex = [...r.examples];
  while (ex.length < 5) ex.push('');
  $('#voiceList').innerHTML = ex.slice(0, 5).map((v, i) => `
    <div class="voice-row">
      <textarea rows="2" placeholder="Paste past tweet #${i + 1}…">${v.replace(/</g, '&lt;')}</textarea>
      <span class="idx">${i + 1}</span>
    </div>`).join('');
}

async function saveVoice(silent = false) {
  const examples = $$('#voiceList textarea').map(t => t.value.trim()).filter(Boolean);
  await api('/api/voice_examples', { method: 'POST', body: { examples } });
  if (!silent) {
    setVerdict('voice', `<span class="tick">✓</span> Saved ${examples.length} sample${examples.length === 1 ? '' : 's'}.`, 'good');
    if (examples.length) confetti(innerWidth / 2, innerHeight / 2, 40);
    setTimeout(() => showStep(step + 1), 700);
  }
  return examples.length;
}

/* ---------------- schedule ---------------- */
function renderPreviewTimes() {
  const n = +$('#postsPerDay').value, s = +$('#startHour').value, e = +$('#endHour').value;
  const box = $('#previewTimes');
  if (e <= s) { box.innerHTML = '<span class="time-pill" style="background:#fdeaea;color:#c0392b">Closing hour must be after opening</span>'; return; }
  const slice = (e - s) / n;
  box.innerHTML = Array.from({ length: n }, (_, i) => {
    const t = s + i * slice + Math.random() * slice;
    const h = Math.floor(t), m = Math.floor((t - h) * 60);
    return `<span class="time-pill" style="animation-delay:${i * .06}s">${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}</span>`;
  }).join('') + '<span class="time-pill" style="background:#eef4f8;color:#5a7286">example — re-rolled daily</span>';
}

async function saveSchedule(silent = false) {
  const body = {
    posts_per_day: +$('#postsPerDay').value,
    start_hour: +$('#startHour').value,
    end_hour: +$('#endHour').value,
  };
  if (body.end_hour <= body.start_hour) { setVerdict('sched', '✕ Closing hour must be after opening hour.', 'bad'); return false; }
  await api('/api/schedule', { method: 'POST', body });
  if (!silent) {
    setVerdict('sched', '<span class="tick">✓</span> Rhythm saved.', 'good');
    setTimeout(() => showStep(step + 1), 650);
  }
  return true;
}

/* ---------------- niche ---------------- */
async function initNiche() {
  if (!state.persona_set) return;
  const r = await api('/api/persona');
  $('#personaText').value = r.persona; $('#nicheTopic').value = r.topic;
  $('#personaOut').classList.remove('hidden'); $('#saveNicheBtn').disabled = false;
}

async function draftPersona() {
  const desc = $('#nicheDesc').value.trim();
  if (desc.length < 15) { setVerdict('niche', '✕ Say a bit more: a sentence or two on what you post about and how you sound.', 'bad'); return; }
  const btn = $('#draftPersonaBtn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Drafting…';
  setVerdict('niche', '<span class="spinner"></span> Writing a persona for you…');
  const r = await api('/api/niche/draft', { method: 'POST', body: { description: desc } });
  btn.disabled = false; btn.textContent = 'Redraft';
  if (!r.ok) { setVerdict('niche', '✕ ' + esc(r.error), 'bad'); return; }
  $('#personaText').value = r.persona; $('#nicheTopic').value = r.topic;
  $('#personaOut').classList.remove('hidden'); $('#saveNicheBtn').disabled = false;
  setVerdict('niche', '<span class="tick">✓</span> Draft ready. Read it over and edit anything that isn\'t you.', 'good');
}

async function saveNiche() {
  const r = await api('/api/persona', { method: 'POST', body: { persona: $('#personaText').value, topic: $('#nicheTopic').value } });
  if (!r.ok) { setVerdict('niche', '✕ ' + esc(r.error), 'bad'); return; }
  state.persona_set = true;
  setVerdict('niche', '<span class="tick">✓</span> Persona saved.', 'good');
  confetti(innerWidth / 2, innerHeight / 2, 40);
  setTimeout(() => showStep(step + 1), 700);
}

/* ---------------- sources ---------------- */
async function loadSources() {
  const [p, ideas] = await Promise.all([api('/api/profile'), api('/api/ideas')]);
  sources.finnhub = p.finnhub;
  sources.feeds = p.feeds.map(url => ({ url }));
  $('#ideasText').value = ideas.ideas.map(i => i.text).join('\n');
  $('#finnhubBlock').open = p.finnhub;
  renderFeeds();
}

function renderFeeds() {
  $('#feedList').innerHTML = sources.feeds.map((f, i) => `
    <li class="feed-item"><span>📰</span>
      <span><b>${esc(f.title || f.url)}</b><i>${f.fresh != null
        ? `${f.fresh} recent stories · ${f.readable ? 'full article text' : 'feed summaries only'}` : esc(f.url)}</i></span>
      <button class="x" data-rm="${i}" type="button" aria-label="Remove feed">✕</button></li>`).join('');
  $$('[data-rm]').forEach(b => b.onclick = () => { sources.feeds.splice(+b.dataset.rm, 1); renderFeeds(); });
}

async function addFeed() {
  const url = $('#feedUrl').value.trim();
  if (!url) return;
  if (sources.feeds.some(f => f.url === url)) { setVerdict('feed', '✕ Already added.', 'bad'); return; }
  const btn = $('#addFeedBtn');
  btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
  setVerdict('feed', '<span class="spinner"></span> Reading the feed…');
  const r = await api('/api/feeds/verify', { method: 'POST', body: { url } });
  btn.disabled = false; btn.textContent = 'Add';
  if (!r.ok) { setVerdict('feed', '✕ ' + esc(r.error), 'bad'); return; }
  sources.feeds.push({ url, title: r.title, fresh: r.fresh, readable: r.readable });
  $('#feedUrl').value = '';
  setVerdict('feed', `<span class="tick">✓</span> ${esc(r.title)}: ${r.fresh} recent stories${r.readable ? '' : ' (the site blocks full-article reading, so the bot will use the feed summaries)'}.`, 'good');
  renderFeeds();
}

async function saveSources() {
  const ideas = $('#ideasText').value.split('\n').map(x => x.trim()).filter(Boolean);
  if (!sources.feeds.length && !ideas.length && !sources.finnhub) {
    setVerdict('sources', '✕ Add at least one feed, one idea, or Finnhub news.', 'bad'); return;
  }
  const btn = $('#saveSourcesBtn'); btn.disabled = true;
  const p = await api('/api/profile', { method: 'POST', body: { feeds: sources.feeds.map(f => f.url), finnhub: sources.finnhub } });
  await api('/api/ideas', { method: 'POST', body: { ideas } });
  btn.disabled = false;
  if (!p.ok) { setVerdict('sources', '✕ ' + esc(Object.values(p.errors)[0]), 'bad'); return; }
  state.has_source = true;
  setVerdict('sources', '<span class="tick">✓</span> Sources saved.', 'good');
  setTimeout(() => showStep(step + 1), 650);
}

/* ---------------- summit ---------------- */
async function celebrateSummit() {
  const st = await api('/api/state');
  const bits = [];
  if (st.profile.feeds.length) bits.push(`${st.profile.feeds.length} feed${st.profile.feeds.length > 1 ? 's' : ''}`);
  if (st.ideas_left) bits.push(`${st.ideas_left} idea${st.ideas_left > 1 ? 's' : ''}`);
  if (st.profile.finnhub) bits.push('Finnhub news');
  const rows = [
    ['🧠', 'Groq connected'],
    ['📮', 'Buffer connected'],
    ['🐦', chosenChannel ? `Posting to ${esc(chosenChannel.name)}` : 'Channel selected'],
    ['🎯', `Persona for ${esc(st.profile.topic)}`],
    ['📡', `Sources: ${esc(bits.join(', ') || 'none yet')}`],
    ['⏰', `${$('#postsPerDay').value} posts/day between ${$('#startHour').value}:00 and ${$('#endHour').value}:00`],
  ];
  $('#summitChecks').innerHTML = rows.map(([i, t]) => `<div><span>${i}</span> ${t}</div>`).join('');
  setTimeout(() => { confetti(innerWidth / 2, innerHeight * .35, 150); }, 350);
}

/* ============================================================
   DASHBOARD
   ============================================================ */
function fmtTime(iso) {
  const d = new Date(iso);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function startCountdown(nextIso) {
  clearInterval(countdownTimer);
  if (!nextIso) { $('#statNext').textContent = '—'; return; }
  const tick = () => {
    const diff = new Date(nextIso) - new Date();
    if (diff <= 0) { $('#statNext').textContent = 'now'; loadDashboard(); return; }
    const h = Math.floor(diff / 3.6e6), m = Math.floor(diff / 6e4) % 60, s = Math.floor(diff / 1000) % 60;
    $('#statNext').textContent = h ? `${h}h ${m}m` : `${m}m ${s}s`;
  };
  tick();
  countdownTimer = setInterval(tick, 1000);
}

async function loadDashboard() {
  state = await api('/api/state');
  const on = state.automation_enabled;

  $('#autoToggle').checked = on;
  $('#statusRing').classList.toggle('live', on);
  $('#statusTitle').textContent = on ? 'Automation running' : 'Automation paused';
  $('#statusSub').textContent = on
    ? `${state.schedule.posts_per_day} posts a day, ${state.schedule.start_hour}:00–${state.schedule.end_hour}:00, randomised.`
    : 'Flip the switch to start posting on schedule.';

  $('#dashSub').textContent = `Automating ${state.profile.topic} posts`;
  $('#sourcesSub').textContent = `${state.profile.feeds.length} feed${state.profile.feeds.length === 1 ? '' : 's'} · ${state.ideas_left} idea${state.ideas_left === 1 ? '' : 's'} left${state.profile.finnhub ? ' · Finnhub' : ''}`;
  $('#statToday').textContent = state.next_posts.length;
  $('#statTotal').textContent = state.total_posts;
  $('#statVoice').textContent = state.voice_examples_count;
  startCountdown(state.next_posts[0]);

  $('#slotList').innerHTML = state.next_posts.length
    ? state.next_posts.map((t, i) => `<li style="animation-delay:${i * .07}s">${fmtTime(t)}</li>`).join('')
    : `<li class="empty">${on ? 'No slots left today — resumes tomorrow.' : 'Automation is off.'}</li>`;

  $('#historyList').innerHTML = state.history.length
    ? state.history.map((h, i) => `<li style="animation-delay:${i * .05}s">
        <time>${new Date(h.timestamp).toLocaleString()}</time><p>${h.text.replace(/</g, '&lt;')}</p></li>`).join('')
    : '<li class="empty">No posts yet — draft one below to get started.</li>';
}

/* ---------------- compose ---------------- */
async function draft() {
  const btn = $('#previewBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Reading your sources…';
  const r = await api('/api/preview', { method: 'POST' });
  btn.disabled = false;
  btn.textContent = 'Draft a post';
  if (!r.ok) { toast(r.error, true); return; }
  $('#composeOut').classList.remove('hidden');
  draftKey = r.key;
  $('#headlineTag').textContent = (r.kind === 'idea' ? '💡 ' : '📰 ') + r.source_headline;
  $('#draftText').value = r.tweet;
  updateCount();
}

function updateCount() {
  const n = $('#draftText').value.length;
  $('#charCount').textContent = `${n} / 280`;
  $('#charCount').classList.toggle('over', n > 280);
}

/* ---------------- modals ---------------- */
function openModal(title, bodyHTML, actions = []) {
  $('#modalTitle').textContent = title;
  $('#modalBody').innerHTML = bodyHTML;
  $('#modalActions').innerHTML = '';
  actions.forEach(a => {
    const b = document.createElement('button');
    b.className = 'btn ' + (a.cls || 'btn-ghost');
    b.textContent = a.label;
    b.onclick = a.fn;
    $('#modalActions').appendChild(b);
  });
  $('#modalBack').classList.remove('hidden');
}
const closeModal = () => $('#modalBack').classList.add('hidden');

async function modalVoice() {
  const r = await api('/api/voice_examples');
  const ex = [...r.examples]; while (ex.length < 5) ex.push('');
  openModal('Voice samples',
    `<p class="panel-note">Five of your own tweets. The model copies your rhythm and capitalisation from these.</p>
     <div class="voice-list">${ex.slice(0, 5).map((v, i) =>
      `<div class="voice-row"><textarea rows="2" placeholder="Past tweet #${i + 1}…">${v.replace(/</g, '&lt;')}</textarea><span class="idx">${i + 1}</span></div>`).join('')}</div>`,
    [{ label: 'Cancel', fn: closeModal },
     { label: 'Save samples', cls: 'btn-primary', fn: async () => {
        const examples = $$('#modalBody textarea').map(t => t.value.trim()).filter(Boolean);
        await api('/api/voice_examples', { method: 'POST', body: { examples } });
        closeModal(); toast(`Saved ${examples.length} voice sample${examples.length === 1 ? '' : 's'}`); loadDashboard();
     } }]);
}

async function modalPlaybook() {
  const r = await api('/api/growth_playbook');
  openModal('Growth playbook',
    `<p class="panel-note">These rules are re-read before every post. Edit freely — changes apply to the next tweet with no restart.</p>
     <textarea id="pbText" rows="18" class="mono">${r.content.replace(/</g, '&lt;')}</textarea>`,
    [{ label: 'Cancel', fn: closeModal },
     { label: 'Save playbook', cls: 'btn-primary', fn: async () => {
        await api('/api/growth_playbook', { method: 'POST', body: { content: $('#pbText').value } });
        closeModal(); toast('Playbook updated');
     } }]);
}

async function modalLogs() {
  const r = await api('/api/logs');
  openModal('Activity log',
    r.lines.length
      ? `<div class="log-lines">${r.lines.map(l => `<div>${l.replace(/</g, '&lt;')}</div>`).join('')}</div>`
      : '<p class="panel-note">Nothing logged yet.</p>',
    [{ label: 'Close', fn: closeModal },
     { label: 'Refresh', cls: 'btn-soft', fn: modalLogs }]);
  const box = $('.log-lines'); if (box) box.scrollTop = box.scrollHeight;
}

async function modalSchedule() {
  const s = state.schedule;
  openModal('Posting rhythm',
    `<p class="panel-note">Posts land at random times inside this window — re-rolled every day.</p>
     <div class="sched-grid">
       <div class="sched-item"><label>Posts per day</label><div class="stepper">
         <button type="button" data-mspin="mPosts" data-dir="-1">−</button>
         <input id="mPosts" type="number" value="${s.posts_per_day}" readonly>
         <button type="button" data-mspin="mPosts" data-dir="1">+</button></div></div>
       <div class="sched-item"><label>Opens</label><div class="stepper">
         <button type="button" data-mspin="mStart" data-dir="-1">−</button>
         <input id="mStart" type="number" value="${s.start_hour}" readonly>
         <button type="button" data-mspin="mStart" data-dir="1">+</button></div></div>
       <div class="sched-item"><label>Closes</label><div class="stepper">
         <button type="button" data-mspin="mEnd" data-dir="-1">−</button>
         <input id="mEnd" type="number" value="${s.end_hour}" readonly>
         <button type="button" data-mspin="mEnd" data-dir="1">+</button></div></div>
     </div>`,
    [{ label: 'Cancel', fn: closeModal },
     { label: 'Save rhythm', cls: 'btn-primary', fn: async () => {
        const body = { posts_per_day: +$('#mPosts').value, start_hour: +$('#mStart').value, end_hour: +$('#mEnd').value };
        if (body.end_hour <= body.start_hour) { toast('Closing hour must be after opening hour', true); return; }
        await api('/api/schedule', { method: 'POST', body });
        closeModal(); toast('Rhythm updated'); loadDashboard();
     } }]);
  $$('[data-mspin]').forEach(b => b.onclick = () => {
    const inp = $('#' + b.dataset.mspin);
    const lim = b.dataset.mspin === 'mPosts' ? [1, 8] : [0, 24];
    inp.value = Math.max(lim[0], Math.min(lim[1], +inp.value + +b.dataset.dir));
  });
}

async function modalSources() {
  const [p, ideas] = await Promise.all([api('/api/profile'), api('/api/ideas')]);
  const canFinnhub = state.finnhub_configured || p.finnhub;
  openModal('Sources',
    `<p class="panel-note">The bot mixes these: it reads stories from your feeds and turns your own notes into posts.</p>
     <label class="modal-label" for="mFeeds">RSS feeds (one address per line)</label>
     <textarea id="mFeeds" rows="4" class="mono" placeholder="https://example.com/feed.xml">${esc(p.feeds.join('\n'))}</textarea>
     <label class="modal-label" for="mIdeas">Idea bank (one per line; ${ideas.ideas.filter(i => i.used).length} already used)</label>
     <textarea id="mIdeas" rows="5" placeholder="Notes, wins, things you learned…">${esc(ideas.ideas.map(i => i.text).join('\n'))}</textarea>
     ${canFinnhub ? `<label class="check-row"><input type="checkbox" id="mFinnhub" ${p.finnhub ? 'checked' : ''}> Also use Finnhub market news</label>` : ''}
     <div class="verdict" id="mVerdict"></div>`,
    [{ label: 'Cancel', fn: closeModal },
     { label: 'Save sources', cls: 'btn-primary', fn: async () => {
        const feeds = $('#mFeeds').value.split('\n').map(x => x.trim()).filter(Boolean);
        const ideasList = $('#mIdeas').value.split('\n').map(x => x.trim()).filter(Boolean);
        const finnhub = $('#mFinnhub') ? $('#mFinnhub').checked : false;
        if (!feeds.length && !ideasList.length && !finnhub) {
          $('#mVerdict').className = 'verdict bad'; $('#mVerdict').textContent = '✕ Keep at least one source, or the bot has nothing to post about.'; return;
        }
        $('#mVerdict').className = 'verdict'; $('#mVerdict').innerHTML = '<span class="spinner"></span> Checking your feeds…';
        const r = await api('/api/profile', { method: 'POST', body: { feeds, finnhub } });
        if (!r.ok) {
          const [url, msg] = Object.entries(r.errors)[0];
          $('#mVerdict').className = 'verdict bad'; $('#mVerdict').textContent = `✕ ${url}: ${msg}`; return;
        }
        await api('/api/ideas', { method: 'POST', body: { ideas: ideasList } });
        closeModal(); toast('Sources saved'); loadDashboard();
     } }]);
}

async function modalPersona() {
  const r = await api('/api/persona');
  openModal('Persona',
    `<p class="panel-note">Who the bot writes as. It's re-read before every post, so edits apply to the next one. Keep the &lt;voice&gt; block.</p>
     <label class="modal-label" for="mTopic">Topic (fills in "today's real ___ stories")</label>
     <input type="text" id="mTopic" class="modal-input" maxlength="40" value="${esc(r.topic)}">
     <label class="modal-label" for="pText">Persona</label>
     <textarea id="pText" rows="14" class="mono">${esc(r.persona)}</textarea>
     <div class="verdict" id="mVerdict"></div>`,
    [{ label: 'Cancel', fn: closeModal },
     { label: 'Save persona', cls: 'btn-primary', fn: async () => {
        const res = await api('/api/persona', { method: 'POST', body: { persona: $('#pText').value, topic: $('#mTopic').value } });
        if (!res.ok) { $('#mVerdict').className = 'verdict bad'; $('#mVerdict').textContent = '✕ ' + res.error; return; }
        closeModal(); toast('Persona updated'); loadDashboard();
     } }]);
}

function modalCloud() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  const cmds = [
    ['1. Push your setup to your private GitHub repo', 'git add -A\ngit commit -m "my setup"\ngit push'],
    ['2. Upload your keys as secrets (they go straight from your .env to GitHub)', 'gh secret set -f .env'],
    ['4. Go live: set your timezone (detected from this browser). This switches the hourly job on', `gh variable set TZ --body ${tz}`],
  ];
  const block = ([label, cmd], i) => `<label class="modal-label">${esc(label)}</label>
       <div class="cmd"><code>${esc(cmd)}</code><button type="button" data-copy="${i}">Copy</button></div>`;
  openModal('Post with your computer off',
    `<p class="panel-note">A free GitHub Actions job runs once an hour, hands each post to Buffer at its exact random time, and saves its state back to your repo. Needs the <a href="https://cli.github.com" target="_blank" rel="noopener">GitHub CLI</a> (<code>gh auth login</code>).</p>
     ${block(cmds[0], 0)}${block(cmds[1], 1)}
     <label class="modal-label">3. Test it</label>
     <p class="panel-note">On GitHub open <b>Actions → post → Run workflow</b> and leave <i>dry run</i> ticked. It writes one post and prints it without publishing.</p>
     ${block(cmds[2], 2)}
     <p class="panel-note"><b>Keep this dashboard's automation switch off</b> while the cloud job is running, or you'll post twice.</p>`,
    [{ label: 'Close', fn: closeModal }]);
  $$('[data-copy]').forEach(b => b.onclick = async () => {
    await navigator.clipboard.writeText(cmds[+b.dataset.copy][1]);
    b.textContent = 'Copied ✓'; setTimeout(() => b.textContent = 'Copy', 1600);
  });
}

async function healthCheck() {
  openModal('Connection health', '<div class="health-list"><div class="health-item"><span class="spinner"></span> Checking all three services…</div></div>', [{ label: 'Close', fn: closeModal }]);
  const rows = [];
  const r = await api('/api/preview', { method: 'POST' });
  rows.push(['📡 Sources + 🧠 Groq', r.ok, r.ok ? 'Read your sources and drafted a post' : r.error]);
  const ch = await api('/api/buffer/channels');
  rows.push(['📮 Buffer', ch.ok, ch.ok ? `${ch.channels.length} channel(s) reachable` : ch.error]);
  $('#modalBody').innerHTML = `<div class="health-list">${rows.map(([n, ok, msg]) =>
    `<div class="health-item ${ok ? 'good' : 'bad'}"><span>${ok ? '✓' : '✕'}</span><span><b>${n}</b><br><small>${msg}</small></span></div>`).join('')}</div>`;
}

/* ============================================================
   WIRING
   ============================================================ */
function wireWizard() {
  $$('[data-next]').forEach(b => b.onclick = () => showStep(step + 1));
  $$('[data-back]').forEach(b => b.onclick = () => showStep(step - 1, -1));
  $$('[data-verify]').forEach(b => b.onclick = () => verify(b.dataset.verify));
  $$('[data-reveal]').forEach(b => b.onclick = () => {
    const i = $('#' + b.dataset.reveal);
    i.type = i.type === 'password' ? 'text' : 'password';
  });
  $$('.field input').forEach(i => i.addEventListener('keydown', e => {
    if (e.key === 'Enter') { const v = e.target.closest('.step-card').querySelector('[data-verify]'); v && v.click(); }
  }));
  $('#refreshChannels').onclick = loadChannels;
  $('#channelNext').onclick = async () => {
    if (!chosenChannel) return;
    await api('/api/buffer/channel', { method: 'POST', body: { channel_id: chosenChannel.id } });
    showStep(step + 1);
  };
  $('#draftPersonaBtn').onclick = draftPersona;
  $('#saveNicheBtn').onclick = saveNiche;
  $('#addFeedBtn').onclick = addFeed;
  $('#feedUrl').addEventListener('keydown', e => { if (e.key === 'Enter') addFeed(); });
  $('#saveSourcesBtn').onclick = saveSources;
  $('#saveVoiceBtn').onclick = () => saveVoice();
  $('#saveSchedBtn').onclick = () => saveSchedule();
  $$('[data-spin]').forEach(b => b.onclick = () => {
    const inp = $('#' + b.dataset.spin);
    const lim = b.dataset.spin === 'postsPerDay' ? [1, 8] : [0, 24];
    inp.value = Math.max(lim[0], Math.min(lim[1], +inp.value + +b.dataset.dir));
    renderPreviewTimes();
  });
  $('#toDashboard').onclick = () => {
    $('#setup-view').classList.add('hidden');
    $('#dashboard-view').classList.remove('hidden');
    loadDashboard();
  };
}

function wireDashboard() {
  $('#autoToggle').onchange = async e => {
    const on = e.target.checked;
    await api(`/api/automation/${on ? 'start' : 'stop'}`, { method: 'POST' });
    toast(on ? 'Automation started — slots scheduled' : 'Automation paused');
    if (on) confetti(innerWidth - 120, 140, 70);
    loadDashboard();
  };
  $('#previewBtn').onclick = draft;
  $('#redraftBtn').onclick = draft;
  $('#draftText').addEventListener('input', updateCount);
  $('#postBtn').onclick = async () => {
    const text = $('#draftText').value.trim();
    if (!text) return toast('Nothing to post', true);
    if (text.length > 280) return toast('Too long for X — trim it first', true);
    openModal('Publish this post?',
      `<p class="panel-note">This goes to your real X account via Buffer, within about 30 seconds.</p>
       <div class="headline-tag" style="border-left-color:var(--mint)">${text.replace(/</g, '&lt;')}</div>`,
      [{ label: 'Cancel', fn: closeModal },
       { label: 'Yes, publish it', cls: 'btn-post', fn: async () => {
          closeModal();
          const btn = $('#postBtn'); btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Sending…';
          const r = await api('/api/post_now', { method: 'POST', body: { tweet: text, key: draftKey } });
          btn.disabled = false; btn.textContent = 'Publish to X';
          if (r.ok) { toast('Sent to Buffer — landing shortly'); confetti(innerWidth / 2, innerHeight / 2, 120); $('#composeOut').classList.add('hidden'); loadDashboard(); }
          else toast(r.error || 'Post failed', true);
       } }]);
  };
  $('#schedBtn').onclick = modalSchedule;
  $('#sourcesBtn').onclick = modalSources;
  $('#personaBtn').onclick = modalPersona;
  $('#cloudBtn').onclick = modalCloud;
  $('#voiceBtn').onclick = modalVoice;
  $('#playbookBtn').onclick = modalPlaybook;
  $('#logsBtn').onclick = modalLogs;
  $('#healthBtn').onclick = healthCheck;
  $('#reSetupBtn').onclick = () => {
    $('#dashboard-view').classList.add('hidden');
    $('#setup-view').classList.remove('hidden');
    showStep(0);
  };
  $('#modalX').onclick = closeModal;
  $('#modalBack').onclick = e => { if (e.target.id === 'modalBack') closeModal(); };
  addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
}

/* ---------------- boot ---------------- */
(async function boot() {
  buildTrail();
  wireWizard();
  wireDashboard();
  state = await api('/api/state');

  $('#postsPerDay').value = state.schedule.posts_per_day;
  $('#startHour').value = state.schedule.start_hour;
  $('#endHour').value = state.schedule.end_hour;

  if (state.setup_complete) {
    $('#setup-view').classList.add('hidden');
    $('#dashboard-view').classList.remove('hidden');
    loadDashboard();
  } else {
    // resume at the first unfinished step
    let start = 0;
    if (state.groq_configured) start = 2;
    if (start === 2 && state.buffer_configured) start = 3;
    if (start === 3 && state.buffer_channel_configured) start = 4;
    if (start === 4 && state.persona_set) start = 5;
    if (start === 5 && state.has_source) start = 6;
    showStep(start);
  }
  setInterval(() => { if (!$('#dashboard-view').classList.contains('hidden') && $('#modalBack').classList.contains('hidden')) loadDashboard(); }, 30000);
})();
