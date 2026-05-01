// ═══════════════════════════════════════════════════════════════════════
//  BIST PREDATOR v35 · Python — TAM OTONOM İZLEME PANELİ
//  Tüm analiz çeşitleri: Teknik, SMC, Çok-TF, Monte Carlo,
//  Hacim/VWAP, Temel Analiz, AI Karar, Formasyonlar
// ═══════════════════════════════════════════════════════════════════════
const BASE = window.location.origin;

async function api(action, params = {}) {
  const url = new URL('/', BASE);
  url.searchParams.set('action', action);
  for (const [k, v] of Object.entries(params)) url.searchParams.set(k, v);
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${action} ${r.status}`);
  return r.json();
}

const $ = (id) => document.getElementById(id);

function fmtPct(v) {
  if (v == null) return '—';
  const n = Number(v);
  const cls = n >= 0 ? 'pnl-pos' : 'pnl-neg';
  return `<span class="${cls}">${n >= 0 ? '+' : ''}${n.toFixed(2)}%</span>`;
}

function aiClass(d) {
  if (d === 'GÜÇLÜ AL') return 'ai-strong';
  if (d === 'AL') return 'ai-buy';
  if (d === 'KAÇIN') return 'ai-warn';
  return 'muted';
}

function nv(v, dec = 2) {
  if (v == null || v === '' || v === undefined) return '—';
  const n = Number(v);
  if (isNaN(n)) return String(v);
  return n.toFixed(dec);
}

function sigColor(v, pos = true) {
  if (v == null) return '#9bb0c7';
  if (pos) return v > 0 ? '#4dd0a8' : '#ec5b5b';
  return v < 0 ? '#4dd0a8' : '#ec5b5b';
}

// ── Hisse Detay Modal ──────────────────────────────────────────────────

let _currentStock = null;
let _stockCache = {};

const TABS = [
  { id: 'ozet',      label: '📊 Özet'          },
  { id: 'tavan',     label: '🚀 Tavan'          },
  { id: 'teknik',    label: '📈 Teknik'         },
  { id: 'formasyonlar', label: '🕯 Formasyonlar' },
  { id: 'smc',       label: '🧩 SMC'            },
  { id: 'multitf',   label: '⏱ Çok TF'         },
  { id: 'monte',     label: '🎲 Monte Carlo'    },
  { id: 'hacim',     label: '📦 Hacim/VWAP'    },
  { id: 'temel',     label: '💹 Temel'          },
  { id: 'ai',        label: '🤖 AI Karar'       },
];

function openStockModal(code, stockData) {
  if ($('stock-modal')) $('stock-modal').remove();
  _currentStock = code;
  _stockCache = {};

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'stock-modal';
  overlay.innerHTML = `
    <div class="modal-card" style="max-width:860px;">
      <div class="modal-head">
        <span class="neon-cy" style="font-size:16px;">🦅 ${code}</span>
        <button class="modal-close" onclick="closeStockModal()">✕</button>
      </div>
      <div class="stock-tabs">
        ${TABS.map(t => `<button class="stab" data-tab="${t.id}" onclick="switchTab('${t.id}')">${t.label}</button>`).join('')}
      </div>
      <div class="modal-body" id="stock-tab-body">
        <div class="muted" style="text-align:center;padding:20px;">Yükleniyor...</div>
      </div>
    </div>
  `;
  overlay.addEventListener('click', e => { if (e.target === overlay) closeStockModal(); });
  document.body.appendChild(overlay);

  switchTab('ozet', stockData);
}

function closeStockModal() {
  const m = $('stock-modal');
  if (m) m.remove();
  _currentStock = null;
}

function switchTab(tabId, prefetch) {
  document.querySelectorAll('.stab').forEach(b => {
    b.classList.toggle('stab-active', b.dataset.tab === tabId);
  });
  const body = $('stock-tab-body');
  if (!body) return;
  body.innerHTML = '<div class="muted" style="text-align:center;padding:20px;">⏳ Yükleniyor...</div>';
  loadTab(tabId, prefetch).then(html => { body.innerHTML = html; }).catch(e => {
    body.innerHTML = `<div class="neon-red" style="padding:16px;">Hata: ${e.message}</div>`;
  });
}

async function loadTab(tabId, prefetch) {
  const code = _currentStock;
  if (!code) return '<div class="muted">Hisse seçilmedi.</div>';

  if (tabId === 'ozet') {
    let s = prefetch || {};
    if (!s.code) {
      const tp = await api('top_picks', { n: 100 });
      s = (tp.picks || []).find(p => p.code === code) || {};
    }
    return renderOzet(code, s);
  }

  if (tabId === 'tavan') {
    const d = await api('tavan_compare', { code });
    return renderTavan(code, d);
  }

  if (tabId === 'teknik') {
    const d = await api('ai_breakdown', { code });
    return renderTeknik(code, d.breakdown || {});
  }

  if (tabId === 'formasyonlar') {
    const d = await api('ai_breakdown', { code });
    const bd = d.breakdown || {};
    const cached = _picksMap[code] || {};
    const forms = bd.formations || bd.formasyonlar || cached.formations || [];
    const items = (bd.items || []).filter(i => {
      const desc = String(i[1] || '').toLowerCase();
      return desc.includes('formasyon') || desc.includes('mum') || desc.includes('bayrak') ||
             desc.includes('çekiç') || desc.includes('yutan') || desc.includes('doji') ||
             desc.includes('yıldız') || desc.includes('marubozu') || desc.includes('harami') ||
             desc.includes('engulf') || desc.includes('üçgen') || desc.includes('kama') ||
             desc.includes('flama') || desc.includes('omuz');
    });
    return renderFormasyonlar(forms, items);
  }

  if (tabId === 'smc') {
    if (!_stockCache.smc) {
      _stockCache.smc = await api('smclevels', { code });
    }
    return renderSMC(_stockCache.smc);
  }

  if (tabId === 'multitf') {
    const d = await api('multi_tf', { code });
    return renderMultiTF(d);
  }

  if (tabId === 'monte') {
    if (!_stockCache.smc) {
      _stockCache.smc = await api('smclevels', { code });
    }
    const mc = _stockCache.smc.monteCarlo || {};
    return renderMonteCarlo(mc, _stockCache.smc);
  }

  if (tabId === 'hacim') {
    if (!_stockCache.smc) {
      _stockCache.smc = await api('smclevels', { code });
    }
    const vp = _stockCache.smc.volProfile || {};
    const vwap = _stockCache.smc.vwapBands || {};
    const avwap = _stockCache.smc.avwap || {};
    return renderHacim(vp, vwap, avwap, _stockCache.smc);
  }

  if (tabId === 'temel') {
    const d = await api('ai_breakdown', { code });
    const bd = d.breakdown || {};
    return renderTemel(bd.fundamental || bd.fin || {}, bd);
  }

  if (tabId === 'ai') {
    const [bd, cs, rs, ex] = await Promise.all([
      api('ai_breakdown', { code }),
      api('consensus_score', { code }).catch(() => ({})),
      api('ai_reasoning', { code }).catch(() => ({})),
      api('ai_explain', { code }).catch(() => ({})),
    ]);
    return renderAI(bd.breakdown || {}, cs.consensus || cs || {}, rs, ex.explain || null);
  }

  return '<div class="muted">Bilinmeyen sekme.</div>';
}

// ── Render fonksiyonları ───────────────────────────────────────────────

function _isYatirimOrtakligi(s) {
  const name = String(s.name || s.code || '').toUpperCase();
  const sham = String(s.sektorHam || '').toUpperCase();
  return name.includes('YATIRIM ORTAKL') || sham.includes('YATIRIM ORTAKL');
}

function renderOzet(code, s) {
  const score = Math.round(s.score || s.predatorScore || 0);
  const dec   = s.autoThinkDecision || s.aiKarar || '—';
  const conf  = s.autoThinkConf || s.aiConf || 0;
  const guncel = nv(s.guncel, 2);
  const h1 = nv(s.h1, 2);
  const h2 = nv(s.h2 || s.targets?.sell2, 2);
  const h3 = nv(s.h3 || s.targets?.sell3, 2);
  const stop = nv(s.stop, 2);
  const rr   = nv(s.rr, 2);
  const rsi  = nv(s.rsi, 0);
  const sektor = s.sektor || '—';
  const mcapRaw = Number(s.marketCap || 0);  // backend: milyon TL biriminde
  const mcap = mcapRaw > 0
    ? (mcapRaw >= 1000 ? `${(mcapRaw/1000).toFixed(2)} Mr₺` : `${mcapRaw.toFixed(1)} M₺`)
    : '—';
  const adil = s.adil ? `${nv(s.adil, 2)}₺` : '—';

  const yoBanner = _isYatirimOrtakligi(s)
    ? `<div class="yo-warning-banner">
        ⚠️ <b>Yatırım Ortaklığı — Stopaj Kesintisi</b>
        <br><span>Bu hisse bir Yatırım Ortaklığıdır (GYO / MKYO / GSYO vb.). Temettü ve gelir dağıtımlarında <b>%10–15 stopaj kesintisi</b> uygulanır. Bu nedenle skorlama sisteminde <b>−100 puan ceza</b> verilmiştir.</span>
       </div>`
    : '';

  return `
    ${yoBanner}
    <div class="reason-block">
      <div class="reason-title">Genel Özet · ${code}</div>
      <table class="bd-table">
        <tr><td>AI Karar</td><td><span class="${aiClass(dec)}" style="font-size:14px;font-weight:bold;">${dec}</span> <small class="muted">%${conf}</small></td></tr>
        <tr><td>Predator Skoru</td><td><b style="color:#00f3ff;">${score}</b></td></tr>
        <tr><td>Güncel Fiyat</td><td>${guncel}₺</td></tr>
        <tr><td>H1 Hedef</td><td class="neon-grn">${h1}₺</td></tr>
        <tr><td>H2 Hedef</td><td class="neon-grn">${h2}₺</td></tr>
        <tr><td>H3 Hedef</td><td class="neon-grn">${h3}₺</td></tr>
        <tr><td>Stop</td><td class="neon-red">${stop}₺</td></tr>
        <tr><td>Risk/Ödül (RR)</td><td>${rr}</td></tr>
        <tr><td>RSI</td><td>${rsi}</td></tr>
        <tr><td>Sektör</td><td>${sektor}</td></tr>
        <tr><td>Piyasa Değeri</td><td>${mcap}</td></tr>
        <tr><td>Adil Değer</td><td>${adil}</td></tr>
      </table>
    </div>
  `;
}

function renderTeknik(code, bd) {
  // bd.items: [[emoji, açıklama, puan], ...]
  const items = bd.items || [];
  const s = _picksMap[code] || {};

  // Hisse cache'inden teknik değerler
  const techRows = [
    ['RSI', s.rsi, v => { const n = Number(v); const c = n < 30 ? '#4dd0a8' : n > 70 ? '#ec5b5b' : '#d6e1f0'; return `<span style="color:${c}">${nv(v, 1)}</span>`; }],
    ['MACD Cross', s.macdCross],
    ['MACD Hist', s.macdHist, v => fmtDir(v)],
    ['RSI Diverjans', s.divRsi, v => fmtSignal(v)],
    ['MACD Diverjans', s.divMacd, v => fmtSignal(v)],
    ['Stochastic K', s.stochK, v => nv(v, 1)],
    ['Stochastic D', s.stochD, v => nv(v, 1)],
    ['Ichimoku', s.ichiSig, v => fmtSignal(v)],
    ['Parabolic SAR', s.sarDir, v => fmtSignal(v)],
    ['Bollinger %B', s.bbPct, v => nv(v, 2)],
    ['Bollinger Squeeze', s.bbSqueeze, v => v ? '<span class="neon-yel">⚡ SIKIŞMA</span>' : 'Hayır'],
    ['Williams %R', s.williamsR, v => nv(v, 1)],
    ['CMF', s.cmf, v => `<span style="color:${Number(v)>0?'#4dd0a8':'#ec5b5b'}">${nv(v,3)}</span>`],
    ['MFI', s.mfi, v => nv(v, 1)],
    ['ADX', s.adxVal, v => nv(v, 1)],
    ['ADX Yön', s.adxDir, v => fmtSignal(v)],
    ['Supertrend Yön', s.supertrendDir, v => fmtSignal(v)],
    ['Supertrend Değer', s.stVal ?? s.supertrendVal ?? s.supertrend?.value, v => `${nv(v, 2)}₺`],
    ['EMA 9 / 21', (s.ema9 != null ? `${nv(s.ema9,2)} / ${nv(s.ema21,2)}` : null)],
    ['EMA Cross', s.emaCrossDir ?? s.emaCross, v => fmtSignal(v)],
    ['EMA Hızlı>Yavaş', s.emaFastAboveSlow ?? s.emaFastAbove, v => v ? '<span class="neon-grn">✓ Üstte</span>' : '<span class="neon-red">✗ Altta</span>'],
    ['Hull MA', s.hullDir, v => fmtSignal(v)],
    ['CMO', s.cmo, v => nv(v, 1)],
    ['Ultimate Osc.', s.ultimateOsc ?? s.uo, v => nv(v, 1)],
    ['PVT', s.pvt, v => fmtDir(v)],
    ['Hacim Oranı', s.volRatio, v => `${nv(v, 2)}x`],
    ['Tüm Zaman Pos', s.pos52wk, v => v != null ? `%${nv(v,1)}` : '—'],
    ['OBV Trend', s.obvTrend, v => fmtSignal(v)],
    ['CCI', s.cci, v => nv(v, 1)],
    ['StochRSI', s.stochRsi, v => nv(v, 2)],
    ['Aroon ↑ / ↓', (s.aroonUp != null ? `${nv(s.aroonUp,0)} / ${nv(s.aroonDown,0)}` : null)],
    ['Aroon Osc.', s.aroonOsc, v => nv(v, 1)],
    ['Awesome Osc.', s.awesomeOscSig, v => fmtSignal(v)],
    ['TRIX Sinyal', s.trixSig, v => fmtSignal(v)],
    ['Elder Sinyal', s.elderSignal, v => fmtSignal(v)],
    ['Keltner Pozisyon', s.keltnerPos, v => fmtSignal(v)],
    ['Fibonacci Pozisyon', s.fibPos, v => fmtSignal(v)],
    ['VWAP Pozisyon', s.vwapPos, v => fmtSignal(v)],
    ['Pivot Aksiyon', s.pivotAction, v => fmtSignal(v)],
    ['Sinyal Kalitesi', s.signalQuality, v => `<b>${nv(v,0)}</b>/100`],
    ['Hız Skoru', s.hizScore, v => nv(v, 0)],
    ['ROC 5/20/60', (s.roc5 != null ? `${nv(s.roc5,2)}% / ${nv(s.roc20,2)}% / ${nv(s.roc60,2)}%` : null)],
  ];

  let html = '<div class="reason-block"><div class="reason-title">Teknik İndikatör Değerleri</div><table class="bd-table">';
  for (const [label, val, fmt] of techRows) {
    if (val == null) continue;
    html += `<tr><td>${label}</td><td>${fmt ? fmt(val) : String(val)}</td></tr>`;
  }
  html += '</table></div>';

  // AI tarafından tetiklenen sinyaller (items listesi)
  if (items.length) {
    const pos = items.filter(i => String(i[2] || '').startsWith('+'));
    const neg = items.filter(i => String(i[2] || '').startsWith('-'));
    if (pos.length) {
      html += '<div class="reason-block"><div class="reason-title">✅ Pozitif Teknik Sinyaller</div><table class="bd-table">';
      pos.forEach(([ico, desc, puan]) => {
        html += `<tr><td>${ico} ${desc}</td><td class="neon-grn">${puan}</td></tr>`;
      });
      html += '</table></div>';
    }
    if (neg.length) {
      html += '<div class="reason-block"><div class="reason-title">⛔ Negatif Teknik Sinyaller</div><table class="bd-table">';
      neg.forEach(([ico, desc, puan]) => {
        html += `<tr><td>${ico} ${desc}</td><td class="neon-red">${puan}</td></tr>`;
      });
      html += '</table></div>';
    }
  }
  return html;
}

function renderFormasyonlar(forms, aiItems) {
  let html = '';

  if (forms && forms.length) {
    const tipLabel = { reversal: 'Dönüş', breakout: 'Kırılım', momentum: 'Momentum', continuation: 'Devam', bearish: 'Ayı', bullish: 'Boğa' };
    html += '<div class="reason-block"><div class="reason-title">Tespit Edilen Formasyonlar</div><table class="bd-table">';
    html += '<tr><th>Formasyon</th><th>Tip</th><th>Güç</th></tr>';
    forms.forEach(f => {
      if (typeof f === 'string') {
        html += `<tr><td>${f}</td><td class="muted">—</td><td class="muted">—</td></tr>`;
        return;
      }
      const name = f.ad || f.name || f.formasyon || '—';
      const emoji = f.emoji || '🔹';
      const tip = f.tip || f.type || '';
      const tipTxt = tipLabel[String(tip).toLowerCase()] || tip || '—';
      const guc = f.guc != null ? f.guc : (f.strength != null ? f.strength : null);
      const renk = f.renk || (tip === 'bearish' ? '#ec5b5b' : '#4dd0a8');
      const gucCell = guc != null ? `<b style="color:${renk}">${guc}</b>` : '<span class="muted">—</span>';
      html += `<tr><td><span style="color:${renk}">${emoji}</span> ${name}</td><td><small style="color:${renk}">${tipTxt}</small></td><td>${gucCell}</td></tr>`;
    });
    html += '</table></div>';
  }

  if (aiItems && aiItems.length) {
    html += '<div class="reason-block"><div class="reason-title">Formasyon Sinyal Etkileri (AI)</div><table class="bd-table">';
    aiItems.forEach(([ico, desc, puan]) => {
      const cls = String(puan).startsWith('+') ? 'neon-grn' : 'neon-red';
      html += `<tr><td>${ico} ${desc}</td><td class="${cls}">${puan}</td></tr>`;
    });
    html += '</table></div>';
  }

  if (!html) {
    html = '<div class="reason-block"><div class="muted" style="padding:12px;">Aktif formasyon tespit edilmedi.</div></div>';
  }
  return html;
}

function renderSMC(d) {
  if (!d || !d.ok) return `<div class="neon-red" style="padding:12px;">${d?.err || 'Veri alınamadı'}</div>`;
  const smc = d.smc || {};
  const ofi = d.ofi || {};
  const harmRaw = d.harmonics;
  const harmList = Array.isArray(harmRaw) ? harmRaw : (harmRaw && Array.isArray(harmRaw.patterns) ? harmRaw.patterns : []);
  const av   = d.adaptiveVol || {};
  const gap  = d.gapAnalysis || {};
  const weekly = d.weeklySignal || {};

  const dirSpan = (t) => {
    const s = String(t || '').toLowerCase();
    if (s.startsWith('bull') || s === 'al' || s === 'buy') return '<span class="neon-grn">⬆ Boğa</span>';
    if (s.startsWith('bear') || s === 'sat' || s === 'sell') return '<span class="neon-red">⬇ Ayı</span>';
    return '<span class="muted">➡ Nötr</span>';
  };

  let html = '';

  // BOS / CHoCH
  const structure = smc.structure || smc.bias || smc.bos || '—';
  html += '<div class="reason-block"><div class="reason-title">Piyasa Yapısı (BOS / CHoCH)</div><table class="bd-table">';
  html += `<tr><td>BOS Yönü</td><td>${fmtSignal(smc.bos)}</td></tr>`;
  if (smc.bosStrength != null) html += `<tr><td>BOS Gücü</td><td>${nv(smc.bosStrength, 2)}%</td></tr>`;
  html += `<tr><td>CHoCH</td><td>${smc.choch ? '<span class="neon-yel">⚡ Karakter Değişimi</span>' : 'Yok'}</td></tr>`;
  html += `<tr><td>Piyasa Yapısı</td><td>${fmtSignal(structure)}</td></tr>`;
  html += '</table></div>';

  // Order Blocks
  if (smc.orderBlocks?.length) {
    html += '<div class="reason-block"><div class="reason-title">Order Blocks (Emir Blokları)</div><table class="bd-table">';
    html += '<tr><th>Yön</th><th>Alt</th><th>Üst</th><th>Güç</th></tr>';
    smc.orderBlocks.slice(0, 6).forEach(ob => {
      const lo = ob.low ?? ob.bot;
      const hi = ob.high ?? ob.top;
      html += `<tr>
        <td>${dirSpan(ob.dir || ob.type)}</td>
        <td>${nv(lo, 2)}</td><td>${nv(hi, 2)}</td><td>${nv(ob.strength, 1)}</td>
      </tr>`;
    });
    html += '</table></div>';
  }

  // Fair Value Gaps
  if (smc.fvg?.length) {
    html += '<div class="reason-block"><div class="reason-title">Fair Value Gaps (Adil Değer Boşlukları)</div><table class="bd-table">';
    html += '<tr><th>Yön</th><th>Alt</th><th>Üst</th><th>Dolu mu?</th></tr>';
    smc.fvg.slice(0, 6).forEach(g => {
      const lo = g.low ?? g.bot;
      const hi = g.high ?? g.top;
      html += `<tr>
        <td>${dirSpan(g.dir || g.type)}</td>
        <td>${nv(lo, 2)}</td><td>${nv(hi, 2)}</td>
        <td>${g.filled ? '<span class="muted">Doldu</span>' : '<span class="neon-cy">Açık</span>'}</td>
      </tr>`;
    });
    html += '</table></div>';
  }

  // Likidite Seviyeleri (swing high/low) + sweep
  const sh = (smc.swingHighs && smc.swingHighs.length) ? smc.swingHighs[smc.swingHighs.length - 1] : null;
  const sl = (smc.swingLows  && smc.swingLows.length)  ? smc.swingLows[smc.swingLows.length - 1]  : null;
  const sweep = smc.liquiditySweep || {};
  if (sh || sl || sweep.bullish || sweep.bearish) {
    html += '<div class="reason-block"><div class="reason-title">Likidite Seviyeleri</div><table class="bd-table">';
    if (sh) html += `<tr><td>Son Swing High</td><td class="neon-red">${nv(sh.price, 2)}</td></tr>`;
    if (sl) html += `<tr><td>Son Swing Low</td><td class="neon-grn">${nv(sl.price, 2)}</td></tr>`;
    if (sweep.bullish) html += `<tr><td>Likidite Süpürme</td><td><span class="neon-yel">⚡ Boğa süpürme (${nv(sweep.strength, 1)})</span></td></tr>`;
    else if (sweep.bearish) html += `<tr><td>Likidite Süpürme</td><td><span class="neon-yel">⚡ Ayı süpürme (${nv(sweep.strength, 1)})</span></td></tr>`;
    html += '</table></div>';
  }

  // OFI
  html += '<div class="reason-block"><div class="reason-title">Emir Akışı Dengesizliği (OFI)</div><table class="bd-table">';
  html += `<tr><td>OFI Değeri</td><td><span style="color:${Number(ofi.ofi) > 0 ? '#4dd0a8' : '#ec5b5b'}">${nv(ofi.ofi, 2)}</span></td></tr>`;
  html += `<tr><td>OFI Sinyali</td><td>${fmtSignal(ofi.signal)}</td></tr>`;
  html += `<tr><td>Trend</td><td>${fmtSignal(ofi.pressure || ofi.trend)}</td></tr>`;
  if (ofi.cumulative != null) html += `<tr><td>Kümülatif</td><td>${nv(ofi.cumulative, 0)}</td></tr>`;
  html += '</table></div>';

  // Harmonik Formasyonlar
  if (harmList.length) {
    html += '<div class="reason-block"><div class="reason-title">Harmonik Formasyonlar</div><table class="bd-table">';
    html += '<tr><th>Formasyon</th><th>Yön</th><th>PRZ</th><th>Güven</th></tr>';
    harmList.slice(0, 5).forEach(p => {
      html += `<tr>
        <td>${p.name || p}</td>
        <td>${dirSpan(p.direction || p.type)}</td>
        <td>${nv(p.prz, 2)}</td>
        <td>${nv(p.confidence, 1)}</td>
      </tr>`;
    });
    html += '</table></div>';
  }

  // Gap Analizi (openGap odaklı)
  const og = gap.openGap || (Array.isArray(gap.gaps) && gap.gaps.length ? gap.gaps[gap.gaps.length - 1] : null);
  html += '<div class="reason-block"><div class="reason-title">Gap (Boşluk) Analizi</div><table class="bd-table">';
  html += `<tr><td>Gap Tipi</td><td>${og ? (og.type === 'up' ? '<span class="neon-grn">⬆ Yukarı</span>' : '<span class="neon-red">⬇ Aşağı</span>') : '—'}</td></tr>`;
  html += `<tr><td>Gap Büyüklüğü</td><td>${og && og.size != null ? `%${nv(og.size, 2)}` : '—'}</td></tr>`;
  html += `<tr><td>Gap Durumu</td><td>${og ? (og.filled ? '<span class="muted">Doldu</span>' : '<span class="neon-cy">Açık</span>') : '—'}</td></tr>`;
  if (gap.gapFillProb != null) html += `<tr><td>Gap Doldurma Olasılığı</td><td>${nv(gap.gapFillProb, 1)}%</td></tr>`;
  if (gap.totalGaps != null) html += `<tr><td>Toplam / Dolan</td><td>${gap.totalGaps} / ${gap.filledGaps ?? 0}</td></tr>`;
  html += '</table></div>';

  // Uyarlanabilir Volatilite
  html += '<div class="reason-block"><div class="reason-title">Uyarlanabilir Volatilite</div><table class="bd-table">';
  html += `<tr><td>Volatilite Rejimi</td><td>${av.regime || '—'}</td></tr>`;
  if (av.realized != null) html += `<tr><td>Realized Vol (yıl.)</td><td>${nv(av.realized, 2)}%</td></tr>`;
  if (av.ewma != null)     html += `<tr><td>EWMA Vol (yıl.)</td><td>${nv(av.ewma, 2)}%</td></tr>`;
  if (av.percentile != null) html += `<tr><td>Vol Yüzdesi</td><td>%${nv(av.percentile, 0)}</td></tr>`;
  html += `<tr><td>ATR</td><td>${nv(d.atr, 3)}</td></tr>`;
  html += `<tr><td>Günlük Vol %</td><td>${nv(d.dailyVol, 2)}%</td></tr>`;
  html += '</table></div>';

  // Haftalık Sinyal
  if (weekly.signal) {
    const wStrength = weekly.strength != null ? weekly.strength : ((weekly.bullScore || 0) - (weekly.bearScore || 0));
    html += '<div class="reason-block"><div class="reason-title">Haftalık Sinyal (W1)</div><table class="bd-table">';
    html += `<tr><td>Sinyal</td><td>${fmtSignal(weekly.signal)}</td></tr>`;
    html += `<tr><td>Trend</td><td>${fmtSignal(weekly.trend)}</td></tr>`;
    html += `<tr><td>RSI (W)</td><td>${nv(weekly.rsi, 1)}</td></tr>`;
    html += `<tr><td>MACD Cross</td><td>${fmtSignal(weekly.macdCross)}</td></tr>`;
    html += `<tr><td>EMA Cross</td><td>${fmtSignal(weekly.emaCross)}</td></tr>`;
    html += `<tr><td>Boğa / Ayı Skoru</td><td><span class="neon-grn">${weekly.bullScore ?? 0}</span> / <span class="neon-red">${weekly.bearScore ?? 0}</span> <small class="muted">(net ${wStrength >= 0 ? '+' : ''}${wStrength})</small></td></tr>`;
    if (weekly.confluence) html += `<tr><td>Konfluans</td><td><span class="neon-yel">⚡ Var</span></td></tr>`;
    html += '</table></div>';
  }

  return html;
}

function renderMultiTF(d) {
  if (!d || !d.ok) return `<div class="neon-red" style="padding:12px;">${d?.err || 'Veri alınamadı'}</div>`;
  const w = d.weekly || {};
  const wStrength = w.strength != null ? w.strength : ((w.bullScore || 0) - (w.bearScore || 0));
  const bonus = Number(d.confluenceBonus || 0);
  const bonusTxt = `${bonus >= 0 ? '+' : ''}${bonus}`;
  const bonusCls = bonus > 0 ? 'neon-grn' : (bonus < 0 ? 'neon-red' : 'muted');

  let html = '<div class="reason-block"><div class="reason-title">Çok Zaman Dilimi Analizi</div><table class="bd-table">';
  html += `<tr><td>Günlük AI Skoru</td><td><b style="color:#00f3ff;">${d.dailyScore || 0}</b></td></tr>`;
  html += `<tr><td>Haftalık Sinyal</td><td>${fmtSignal(w.signal)}</td></tr>`;
  html += `<tr><td>Haftalık Trend</td><td>${fmtSignal(w.trend)}</td></tr>`;
  html += `<tr><td>Haftalık Net Güç</td><td>${wStrength >= 0 ? '+' : ''}${wStrength}</td></tr>`;
  html += `<tr><td>Haftalık RSI</td><td>${nv(w.rsi, 1)}</td></tr>`;
  html += `<tr><td>Haftalık MACD Cross</td><td>${fmtSignal(w.macdCross)}</td></tr>`;
  html += `<tr><td>Haftalık EMA Cross</td><td>${fmtSignal(w.emaCross)}</td></tr>`;
  if (w.sma20 != null) html += `<tr><td>SMA 20 / 50</td><td>${nv(w.sma20, 2)} / ${nv(w.sma50, 2)}</td></tr>`;
  html += `<tr><td>Boğa / Ayı Skoru</td><td><span class="neon-grn">${w.bullScore ?? 0}</span> / <span class="neon-red">${w.bearScore ?? 0}</span></td></tr>`;
  if (w.confluence) html += `<tr><td>Konfluans</td><td><span class="neon-yel">⚡ Var</span></td></tr>`;
  html += `<tr><td>MTF Uyum Bonusu</td><td><span class="${bonusCls}">${bonusTxt}</span></td></tr>`;
  html += `<tr><td>Final Skor</td><td><b class="neon-cy">${d.finalScore || 0}</b></td></tr>`;
  html += '</table></div>';
  return html;
}

function renderMonteCarlo(mc, d) {
  if (!mc || (mc.win_prob == null && mc.iters == null)) {
    return `<div class="reason-block"><div class="muted" style="padding:12px;">Monte Carlo verisi yok. SMC sekmesini ziyaret edip tekrar deneyin.</div></div>`;
  }
  const kelly = d?.kelly || {};
  let html = '<div class="reason-block"><div class="reason-title">Monte Carlo Risk Simülasyonu</div><table class="bd-table">';
  html += `<tr><td>Kazanma Olasılığı (H1)</td><td><b class="neon-grn">${nv(mc.win_prob, 1)}%</b></td></tr>`;
  html += `<tr><td>H2 Olasılığı</td><td>${nv(mc.h2_prob, 1)}%</td></tr>`;
  html += `<tr><td>Stop Olasılığı</td><td><span class="neon-red">${nv(mc.stop_prob, 1)}%</span></td></tr>`;
  html += `<tr><td>Medyan Getiri</td><td>${fmtPct(mc.median_ret)}</td></tr>`;
  html += `<tr><td>Beklenen Değer</td><td>${fmtPct(mc.ev)}</td></tr>`;
  html += `<tr><td>En İyi %5</td><td class="neon-grn">${nv(mc.p95, 2)}%</td></tr>`;
  html += `<tr><td>En Kötü %5</td><td class="neon-red">${nv(mc.p5, 2)}%</td></tr>`;
  html += `<tr><td>Sharpe Tahmini</td><td>${nv(mc.sharpe, 2)}</td></tr>`;
  html += `<tr><td>Simülasyon Sayısı</td><td>${mc.iters || 500}</td></tr>`;
  html += '</table></div>';

  if (kelly.position_size != null) {
    html += '<div class="reason-block"><div class="reason-title">Kelly Kriteri · Pozisyon Büyüklüğü</div><table class="bd-table">';
    html += `<tr><td>Kelly Fraksiyonu</td><td>${nv(kelly.kelly_frac * 100, 1)}%</td></tr>`;
    html += `<tr><td>Önerilen Pozisyon</td><td><b class="neon-cy">${nv(kelly.position_size, 0)}₺</b></td></tr>`;
    html += `<tr><td>Max Risk</td><td class="neon-red">${nv(kelly.max_risk_tl, 0)}₺</td></tr>`;
    html += `<tr><td>Lot (100₺)</td><td>${nv(kelly.lots_100, 0)}</td></tr>`;
    html += '</table></div>';
  }
  return html;
}

function renderHacim(vp, vwap, avwap, d) {
  let html = '';

  // Volume Profile
  const av = (d && d.adaptiveVol) || {};
  const fmtList = (arr) => (Array.isArray(arr) && arr.length ? arr.slice(0,5).map(x => `${nv(x,2)}₺`).join(' · ') : '—');
  html += '<div class="reason-block"><div class="reason-title">Hacim Profili</div><table class="bd-table">';
  html += `<tr><td>POC (En Çok İşlem)</td><td><b class="neon-cy">${nv(vp.poc, 2)}₺</b></td></tr>`;
  html += `<tr><td>Değer Alanı Üst (VAH)</td><td>${nv(vp.vah, 2)}₺</td></tr>`;
  html += `<tr><td>Değer Alanı Alt (VAL)</td><td>${nv(vp.val, 2)}₺</td></tr>`;
  html += `<tr><td>HVN (Yüksek Hacim)</td><td>${fmtList(vp.hvn)}</td></tr>`;
  html += `<tr><td>LVN (Düşük Hacim)</td><td>${fmtList(vp.lvn)}</td></tr>`;
  if (av.regime) html += `<tr><td>Volatilite Rejimi</td><td>${av.regime}</td></tr>`;
  html += '</table></div>';

  // VWAP Bantları
  html += '<div class="reason-block"><div class="reason-title">VWAP Bantları</div><table class="bd-table">';
  html += `<tr><td>VWAP</td><td><b>${nv(vwap.vwap, 2)}₺</b></td></tr>`;
  html += `<tr><td>Üst Bant (+1σ)</td><td class="neon-red">${nv(vwap.upper1, 2)}₺</td></tr>`;
  html += `<tr><td>Üst Bant (+2σ)</td><td class="neon-red">${nv(vwap.upper2, 2)}₺</td></tr>`;
  html += `<tr><td>Alt Bant (-1σ)</td><td class="neon-grn">${nv(vwap.lower1, 2)}₺</td></tr>`;
  html += `<tr><td>Alt Bant (-2σ)</td><td class="neon-grn">${nv(vwap.lower2, 2)}₺</td></tr>`;
  const vwapSig = vwap.signal || ({
    ust2: 'Çok yüksek (+2σ üstü)',
    ust1: 'Yüksek (+1σ üstü)',
    icinde: 'Bant içi',
    alt1: 'Düşük (-1σ altı)',
    alt2: 'Çok düşük (-2σ altı)',
  }[vwap.position] || '—');
  html += `<tr><td>VWAP Sinyali</td><td>${fmtSignal(vwapSig)}</td></tr>`;
  if (vwap.dev != null) html += `<tr><td>σ Sapması</td><td>${nv(vwap.dev, 2)}</td></tr>`;
  html += '</table></div>';

  // AVWAP Stratejileri
  const anchors = (avwap && avwap.anchors) ? avwap.anchors : null;
  if (anchors && Object.keys(anchors).length) {
    html += '<div class="reason-block"><div class="reason-title">Bağlantılı VWAP (AVWAP) Stratejileri</div><table class="bd-table">';
    Object.entries(anchors).forEach(([k, v]) => {
      if (!v || typeof v !== 'object') return;
      const label = v.label || k;
      const diff = v.diffPct != null ? ` <small class="muted">(%${nv(v.diffPct, 2)})</small>` : '';
      html += `<tr><td><b>${label}</b></td><td>${nv(v.avwap, 2)}₺${diff}</td></tr>`;
    });
    html += '</table></div>';

    const sum = avwap.summary || {};
    if (sum.bias) {
      html += '<div class="reason-block"><div class="reason-title">AVWAP Özet</div><table class="bd-table">';
      html += `<tr><td>Genel Eğilim</td><td>${fmtSignal(sum.bias)}</td></tr>`;
      html += `<tr><td>Boğa / Ayı Puanı</td><td><span class="neon-grn">${sum.bullPts ?? 0}</span> / <span class="neon-red">${sum.bearPts ?? 0}</span></td></tr>`;
      html += '</table></div>';
    }

    const sigs = Array.isArray(avwap.signals) ? avwap.signals : [];
    if (sigs.length) {
      html += '<div class="reason-block"><div class="reason-title">AVWAP Sinyalleri</div><ul style="margin:6px 0 0 18px;padding:0;">';
      sigs.forEach(s => { html += `<li>${s.msg || ''}</li>`; });
      html += '</ul></div>';
    }
  }

  return html;
}

function renderTemel(fin, bd) {
  fin = fin || {};
  const fmtMoney = (v) => {
    const n = Number(v);
    if (!isFinite(n) || n === 0) return '—';
    const abs = Math.abs(n);
    const sign = n < 0 ? '-' : '';
    if (abs >= 1e9) return `${sign}${(abs/1e9).toFixed(2)} Mr₺`;
    if (abs >= 1e6) return `${sign}${(abs/1e6).toFixed(2)} M₺`;
    if (abs >= 1e3) return `${sign}${(abs/1e3).toFixed(1)} K₺`;
    return `${sign}${abs.toFixed(0)}₺`;
  };
  const fmtPctVal = (v) => v == null ? '—' : `%${nv(v, 2)}`;
  const fmtRatio  = (v) => v == null ? '—' : nv(v, 2);
  const fmtBool   = (v) => v ? '<span class="neon-grn">✓ Var</span>' : '<span class="muted">Yok</span>';
  const colorPct  = (v, good=true) => {
    const n = Number(v); if (!isFinite(n)) return fmtPctVal(v);
    const cls = (good ? n > 0 : n < 0) ? 'neon-grn' : (n === 0 ? 'muted' : 'neon-red');
    return `<span class="${cls}">${fmtPctVal(v)}</span>`;
  };

  const netKar = fin.NetKar ?? fin.netKar ?? fin.sonDortCeyrek;

  const metrics = [
    ['Net Kâr (Son 4 Çeyrek)', fmtMoney(netKar)],
    ['F/K Oranı',              fin.FK ?? fin.fk, fmtRatio],
    ['Piyasa / Defter Değeri', fin.PiyDegDefterDeg ?? fin.pddd, fmtRatio],
    ['ROE',                    fin.roe, colorPct],
    ['ROA',                    fin.roa, colorPct],
    ['Net Kâr Marjı',          fin.netKarMarj, colorPct],
    ['Faaliyet Kâr Marjı',     fin.faalKarMarj, colorPct],
    ['Brüt Kâr Marjı',         fin.brutKarMarj, colorPct],
    ['Cari Oran',              fin.cariOran, fmtRatio],
    ['Borç / Özkaynak',        fin.borcOz, fmtRatio],
    ['Nakit Oran',             fin.nakitOran, fmtRatio],
    ['Likidite Oranı',         fin.likitOran, fmtRatio],
    ['Kaldıraç',               fin.kaldiraci, fmtRatio],
    ['Stok Devir Hızı',        fin.stokDevirH, fmtRatio],
    ['Alacak Devir Hızı',      fin.alacakDevirH, fmtRatio],
    ['Aktif Devir',            fin.aktifDevir, fmtRatio],
    ['Kısa Vadeli Borç Oranı', fin.kvsaBorcOran, fmtRatio],
    ['Net Para Akışı',         fmtMoney(fin.netParaAkis)],
    ['Para Girişi',            fmtMoney(fin.paraGiris)],
    ['Halka Açıklık (%)',      fin.halkakAciklik, fmtPctVal],
    ['Son Temettü (%)',        fin.lastTemettu, fmtPctVal],
    ['3 Aylık Getiri',         fin.ret3m, colorPct],
    ['Tabana Mesafe (%)',      fin.tabanFark, fmtPctVal],
    ['Yakın Bedelsiz',         fin.recentBedelsiz, fmtBool],
  ];

  const isPresent = (raw) => {
    if (raw == null) return false;
    if (typeof raw === 'string') return raw !== '—' && raw !== '';
    if (typeof raw === 'boolean') return true;
    return true;
  };
  const hasData = metrics.some(([, v]) => isPresent(v));
  if (!hasData) {
    return '<div class="reason-block"><div class="muted" style="padding:12px;">Temel finansal veri bulunamadı. Hisse için API verisi henüz mevcut olmayabilir.</div></div>';
  }

  let html = '<div class="reason-block"><div class="reason-title">Temel Analiz · Finansal Göstergeler</div><table class="bd-table">';
  metrics.forEach(([label, raw, fmt]) => {
    if (!isPresent(raw)) return;
    const cell = fmt ? fmt(raw) : raw;
    html += `<tr><td>${label}</td><td>${cell}</td></tr>`;
  });
  html += '</table></div>';

  if (bd && bd.fundamentalScore != null) {
    html += `<div class="reason-block"><div class="reason-title">Temel Skor</div>
      <p style="font-size:20px;color:#00f3ff;margin:8px 0;">${bd.fundamentalScore} / 100</p>
    </div>`;
  }
  return html;
}

function renderAI(bd, cs, rs, ex) {
  let html = '';

  // ── v37.3: AI Şeffaflık Paneli — fazlara ayrılmış tam karar kırılımı ──
  if (ex && Array.isArray(ex.phases)) {
    const conf = ex.confidence ?? 0;
    const confCls = conf >= 70 ? 'neon-grn' : (conf <= 40 ? 'neon-red' : 'neon-cy');
    const decCls = aiClass(ex.decision);
    html += '<div class="reason-block" style="border-left:3px solid #00e5ff;">';
    html += '<div class="reason-title">🧠 AI Şeffaflık Paneli — Karar Nasıl Oluştu?</div>';
    html += '<table class="bd-table">';
    html += `<tr><td>Final Karar</td><td><span class="${decCls}" style="font-size:14px;font-weight:bold;">${ex.decision || '—'}</span></td></tr>`;
    html += `<tr><td>AI Skoru (final)</td><td><b class="neon-cy">${ex.aiScore}</b> / 1000</td></tr>`;
    html += `<tr><td>Al Puanı (taban)</td><td><b>${ex.alPuani}</b> / 800</td></tr>`;
    html += `<tr><td>AI Güven Seviyesi</td><td><b class="${confCls}">%${conf}</b> <small class="muted">(NN uyumu + örnek sayısı + sinyal yoğunluğu)</small></td></tr>`;
    html += `<tr><td>Pozitif / Negatif Sinyal</td><td><span class="neon-grn">+${ex.pos_signals}</span> &nbsp;/&nbsp; <span class="neon-red">-${ex.neg_signals}</span></td></tr>`;
    html += '</table></div>';

    // Anomali uyarıları
    if (ex.anomalies && ex.anomalies.length) {
      html += '<div class="reason-block" style="border-left:3px solid #ff9800;">';
      html += '<div class="reason-title">⚠️ Çelişen / Dikkat Gerektiren Sinyaller</div>';
      html += '<table class="bd-table">';
      ex.anomalies.forEach(a => {
        html += `<tr><td colspan="2" style="color:#ffc107;">${a}</td></tr>`;
      });
      html += '</table></div>';
    }

    // Her fazın detayı
    ex.phases.forEach(ph => {
      const pts = ph.points || 0;
      const ptsCls = pts > 0 ? 'neon-grn' : (pts < 0 ? 'neon-red' : 'muted');
      const ptsTxt = pts > 0 ? `+${pts}` : `${pts}`;
      html += '<div class="reason-block">';
      html += `<div class="reason-title">${ph.name} <span class="${ptsCls}" style="float:right;font-weight:bold;">${ptsTxt} puan</span></div>`;
      html += '<table class="bd-table">';
      (ph.items || []).forEach(([label, val, cls]) => {
        const c = cls || 'muted';
        html += `<tr><td>${label}</td><td class="${c}">${val}</td></tr>`;
      });
      html += '</table></div>';
    });
  }


  // bd.items: [[emoji, açıklama, puan], ...] — tüm AI karar kırılımı
  const items = bd.items || [];
  const aiScore = bd.aiScore;
  const alPuani = bd.alPuani;
  const mode = bd.mode;
  const toplam = bd.toplam || items.length;

  // AI Karar Özeti
  html += '<div class="reason-block"><div class="reason-title">AI Karar Kırılımı</div><table class="bd-table">';
  html += `<tr><td>AI Skoru</td><td><b class="neon-cy">${aiScore != null ? aiScore : '—'}</b></td></tr>`;
  html += `<tr><td>Al Puanı</td><td>${alPuani != null ? alPuani : '—'}</td></tr>`;
  html += `<tr><td>Piyasa Modu</td><td>${mode || '—'}</td></tr>`;
  html += `<tr><td>Toplam Sinyal</td><td>${toplam}</td></tr>`;
  if (items.length) {
    const posSum = items.filter(i => String(i[2]||'').startsWith('+')).reduce((a, i) => a + parseInt(String(i[2]).replace('+','')||0), 0);
    const negSum = items.filter(i => String(i[2]||'').startsWith('-')).reduce((a, i) => a + parseInt(String(i[2])||0), 0);
    html += `<tr><td>Pozitif Katkı</td><td class="neon-grn">+${posSum}</td></tr>`;
    html += `<tr><td>Negatif Katkı</td><td class="neon-red">${negSum}</td></tr>`;
  }
  html += '</table></div>';

  // Konsensüs Skoru
  const consensusVal = cs && typeof cs === 'object' ? (cs.score ?? cs.consensus) : null;
  if (cs && consensusVal != null) {
    html += '<div class="reason-block"><div class="reason-title">Konsensüs Skoru</div><table class="bd-table">';
    html += `<tr><td>Konsensüs</td><td><b class="neon-cy">${nv(consensusVal, 1)} / 100</b></td></tr>`;
    if (cs.avg != null)         html += `<tr><td>Ağırlıklı Ortalama</td><td>${nv(cs.avg, 1)}</td></tr>`;
    if (cs.agree_bull != null)  html += `<tr><td>Boğa Uyumu</td><td><span class="neon-grn">${cs.agree_bull} sistem</span></td></tr>`;
    if (cs.agree_bear != null)  html += `<tr><td>Ayı Uyumu</td><td><span class="neon-red">${cs.agree_bear} sistem</span></td></tr>`;
    if (cs.ai_score_bonus != null) html += `<tr><td>AI Skor Bonusu</td><td>${cs.ai_score_bonus >= 0 ? '+' : ''}${cs.ai_score_bonus}</td></tr>`;
    html += '</table></div>';

    if (Array.isArray(cs.scores) && Array.isArray(cs.names) && cs.scores.length === cs.names.length) {
      html += '<div class="reason-block"><div class="reason-title">8 Sistem Kırılımı</div><table class="bd-table">';
      cs.names.forEach((nm, i) => {
        const sc = Number(cs.scores[i] || 0);
        const cls = sc >= 60 ? 'neon-grn' : (sc <= 40 ? 'neon-red' : 'muted');
        html += `<tr><td>${nm}</td><td class="${cls}"><b>${sc}</b></td></tr>`;
      });
      html += '</table></div>';
    }
  }

  // Tüm AI sinyal kırılımı
  if (items.length) {
    html += '<div class="reason-block"><div class="reason-title">Tüm Sinyal Detayları</div><table class="bd-table">';
    items.forEach(([ico, desc, puan]) => {
      const cls = String(puan).startsWith('+') ? 'neon-grn' : (String(puan).startsWith('-') ? 'neon-red' : 'muted');
      html += `<tr><td>${ico} ${desc}</td><td class="${cls}" style="font-weight:bold;">${puan}</td></tr>`;
    });
    html += '</table></div>';
  }

  // AI Gerekçesi
  if (rs) {
    const text = rs.reasoning || rs.text || rs.reason || rs.gerekce || '';
    if (text) {
      html += `<div class="reason-block"><div class="reason-title">AI Gerekçesi</div><pre class="reason-pre">${text}</pre></div>`;
    }
    if (rs.ok === false && rs.err) {
      html += `<div class="reason-block"><div class="muted">AI gerekçesi: ${rs.err}</div></div>`;
    }
  }

  if (!items.length && !html.includes('neon-cy')) {
    html += '<div class="reason-block"><div class="muted" style="padding:12px;">AI detay verisi bu hisse için henüz oluşturulmamış.</div></div>';
  }
  return html;
}

// ── Yardımcı formatlama ────────────────────────────────────────────────

function fmtSignal(v) {
  if (v == null) return '—';
  const s = String(v).toLowerCase();
  if (s === 'bull' || s === 'bullish' || s === 'al' || s === 'buy' || s === 'up' || s === 'long' || s === '1' || s === 'true') {
    return '<span class="neon-grn">⬆ Boğa/Al</span>';
  }
  if (s === 'bear' || s === 'bearish' || s === 'sat' || s === 'sell' || s === 'down' || s === 'short' || s === '-1') {
    return '<span class="neon-red">⬇ Ayı/Sat</span>';
  }
  if (s === 'notr' || s === 'neutral' || s === 'yan' || s === '0') {
    return '<span class="muted">➡ Nötr</span>';
  }
  return `<span style="color:#d6e1f0;">${v}</span>`;
}

function fmtDir(v) {
  if (v == null) return '—';
  const n = Number(v);
  if (!isNaN(n)) return `<span style="color:${n > 0 ? '#4dd0a8' : '#ec5b5b'}">${n > 0 ? '⬆' : '⬇'} ${nv(v, 4)}</span>`;
  return fmtSignal(v);
}

function yonIcon(y) {
  if (!y) return '';
  const s = String(y).toLowerCase();
  if (s.includes('bull') || s.includes('al') || s.includes('buy')) return '🟢';
  if (s.includes('bear') || s.includes('sat') || s.includes('sell')) return '🔴';
  return '⚪';
}

function yonLabel(y) {
  if (!y) return '';
  const s = String(y).toLowerCase();
  if (s.includes('bull') || s.includes('al') || s.includes('buy')) return 'Boğa';
  if (s.includes('bear') || s.includes('sat') || s.includes('sell')) return 'Ayı';
  return 'Nötr';
}

// ── Global hisse önbelleği (modal için) ────────────────────────────────
const _picksMap = {};

// ── Ana Panel Fonksiyonları ────────────────────────────────────────────

// ── Filtre durumu (Tümü / Uyuyan / Erken / AL) ──────────────────────
let _picksAll = [];
let _picksFilter = 'all';
let _kapTipeMap = {};   // { CODE: {ageDays, baslik, link, tarih, pos52wk} }

function _matchFilter(p, f) {
  if (f === 'sleeper') return (p.sleeperBonus || 0) >= 50;
  if (f === 'early')   return (p.earlyCatchBonus || 0) >= 10;
  if (f === 'sibling') return (p.siblingBonus || 0) > 0;
  if (f === 'tipe')    return _kapTipeMap[p.code] != null;
  if (f === 'buy') {
    const d = (p.autoThinkDecision || '').toUpperCase();
    return d === 'AL' || d === 'GÜÇLÜ AL' || d === 'GUCLU AL';
  }
  if (f === 'ipo')     return !!p.ipoAltinda && (p.ipoFiyat || 0) > 0;
  if (f === 'tavan')   return (p.isTavan === true) ||
                              ((p.tavanInfo && p.tavanInfo.isYakin) === true) ||
                              (Number(p.nextTavanScore || 0) >= 20);
  if (f === 'katlama') return p.katlamis === true ||
                              ((p.katlamaInfo || {}).isKatlamis === true);
  if (f === 'bedelsiz') return (p.kapBedelsizBonus || 0) > 0;
  return true;
}

function _renderKatlamaHedefleri(p) {
  const ki = p.katlamaInfo || {};
  const guncel = p.guncel || 0;

  // Önce katlamaInfo'dan al, yoksa eski h1/h2/h3
  const kh1 = ki.h1 || p.h1 || 0;
  const kh2 = ki.h2 || p.h2 || 0;
  const kh3 = ki.h3 || p.h3 || 0;
  const kh1Pct = ki.h1Pct != null ? ki.h1Pct : (guncel > 0 && kh1 > guncel ? +((kh1 - guncel) / guncel * 100).toFixed(1) : 0);
  const kh2Pct = ki.h2Pct != null ? ki.h2Pct : (guncel > 0 && kh2 > guncel ? +((kh2 - guncel) / guncel * 100).toFixed(1) : 0);
  const kh3Pct = ki.h3Pct != null ? ki.h3Pct : (guncel > 0 && kh3 > guncel ? +((kh3 - guncel) / guncel * 100).toFixed(1) : 0);
  const ks     = ki.katlamaScore || 0;
  const klvl   = ki.katlamaLevel || '';

  const lvlClass = klvl === '5X' ? 'klvl-5x'
                 : klvl === '3X' ? 'klvl-3x'
                 : klvl === '2X' ? 'klvl-2x'
                 : klvl === '1.5X' ? 'klvl-15x'
                 : '';
  const lvlBadge = klvl && klvl !== 'NORMAL'
    ? `<span class="klvl-badge ${lvlClass}" title="Katlama Skoru: ${ks}">${klvl}</span>`
    : (ks > 0 ? `<span class="klvl-score" title="Katlama Skoru">${ks}</span>` : '');

  const h1Src = ki.h1Src ? ` title="${ki.h1Src}"` : '';
  const h2Src = ki.h2Src ? ` title="${ki.h2Src}"` : '';
  const h3Src = ki.h3Src ? ` title="${ki.h3Src}"` : '';

  const pctFmt = v => v > 0 ? `<span class="kpct pos">+${v.toFixed(0)}%</span>` :
                       v < 0 ? `<span class="kpct neg">${v.toFixed(0)}%</span>` : '';

  if (!kh1 && !kh2 && !kh3) return '<small class="muted">—</small>';

  return `<div class="kh-wrap">
    ${kh1 > 0 ? `<div class="kh-row"${h1Src}><span class="kh-lbl">H1</span><b>${kh1.toFixed(2)}₺</b>${pctFmt(kh1Pct)}</div>` : ''}
    ${kh2 > 0 ? `<div class="kh-row"${h2Src}><span class="kh-lbl">H2</span><b>${kh2.toFixed(2)}₺</b>${pctFmt(kh2Pct)}</div>` : ''}
    ${kh3 > 0 ? `<div class="kh-row"${h3Src}><span class="kh-lbl">H3</span><b>${kh3.toFixed(2)}₺</b>${pctFmt(kh3Pct)} ${lvlBadge}</div>` : ''}
  </div>`;
}

function _renderPicksTable() {
  const body = $('picks-body');
  if (!_picksAll.length) {
    body.innerHTML = '<tr><td colspan="17" class="muted">İlk tarama bekleniyor...</td></tr>';
    return;
  }
  const list = _picksAll.filter(p => _matchFilter(p, _picksFilter));
  if (!list.length) {
    body.innerHTML = `<tr><td colspan="17" class="muted">Bu filtreye uyan hisse yok</td></tr>`;
    return;
  }
  body.innerHTML = list.map((p, i) => {
    const sb = p.sleeperBonus || 0;
    const eb = p.earlyCatchBonus || 0;
    const xb = p.siblingBonus || 0;
    const ib = p.ipoBonus || 0;
    const ifk = (typeof p.ipoFark === 'number') ? p.ipoFark : null;
    const ifyat = p.ipoFiyat || 0;
    const tipe = _kapTipeMap[p.code] || null;
    const sBadge = sb >= 50 ? `<span class="sleeper-badge" title="Uyuyan Mücevher Bonusu">+${sb}</span>` :
                   sb > 0  ? `<span class="sleeper-badge dim">+${sb}</span>` : '<small class="muted">—</small>';
    const eBadge = eb >= 10 ? `<span class="early-badge" title="Erken Yakalama Bonusu">+${eb}</span>` :
                   eb > 0  ? `<span class="early-badge dim">+${eb}</span>` : '<small class="muted">—</small>';
    let iBadge = '<small class="muted">—</small>';
    if (ifyat > 0 && ifk !== null) {
      const farkTxt = (ifk >= 0 ? '+' : '') + ifk.toFixed(1) + '%';
      const tip = `Halka Arz Fiyatı: ${ifyat.toFixed(2)}₺ · Cari fark: ${farkTxt}` + (ib > 0 ? ` · Skor bonusu: +${ib}` : '');
      const cls = ifk <= -25 ? 'ipo-badge deep'
                : ifk <=   0 ? 'ipo-badge under'
                : ifk <=   5 ? 'ipo-badge near'
                : 'ipo-badge dim';
      iBadge = `<span class="${cls}" title="${tip.replace(/"/g,'&quot;')}">${farkTxt}${ib>0?` <small>+${ib}</small>`:''}</span>`;
    }
    let xBadge = '<small class="muted">—</small>';
    if (xb > 0) {
      const ref = p.siblingRefCode || '?';
      const pdo = p.siblingPdOrani ? ` ${Math.round(p.siblingPdOrani)}x` : '';
      const tip = `${p.siblingOrtakAd || ''} ortağıyla ${ref} (${p.siblingType === 'kucuk_kardes' ? 'büyük kardeş' : 'abi katlamış'})`;
      xBadge = `<span class="sibling-badge" title="${tip.replace(/"/g,'&quot;')}">+${xb}<small>${pdo}</small></span>`;
    }
    let tBadge = '<small class="muted">—</small>';
    if (tipe) {
      const pos = Number(tipe.pos52wk || 0);
      // Renk dip derinliğine göre — yaş artık skor üzerinde etkili değil
      const cls = pos < 10 ? '' : (pos < 20 ? ' recent' : ' old');
      const tip = (tipe.baslik || 'KAP Tipe Dönüşüm').replace(/"/g,'&quot;');
      tBadge = `<span class="tipe-badge${cls}" title="${tip} — ${tipe.tarih || ''} · Tüm zaman dip %${Math.round(pos)}">📜</span>`;
    }
    // 🚀 Tavan / Katlama rozeti
    // 🎁 Bedelsiz / Rüçhan rozeti
    let bBadge = '<small class="muted">—</small>';
    const bedBonus = Number(p.kapBedelsizBonus || 0);
    if (bedBonus > 0) {
      const bedItems = p.kapBedelsizItems || [];
      const hasRuchan = bedItems.some(it => String(it[1] || '').toLowerCase().includes('rüçhan'));
      const label   = hasRuchan ? '💰 Rüçhan' : '🎁 Bedelsiz';
      const tipTxt  = bedItems.length
        ? bedItems.map(it => String(it[1] || '')).join(' | ').slice(0, 120)
        : 'KAP Bedelsiz/Rüçhan başvuru';
      const bedCls  = hasRuchan ? 'ruchan-badge' : 'bedelsiz-badge';
      bBadge = `<span class="${bedCls}" title="${tipTxt.replace(/"/g,'&quot;')}">${label} <small>+${bedBonus}</small></span>`;
    }

    let rBadge = '<small class="muted">—</small>';
    const isT  = (p.isTavan === true) || ((p.tavanInfo || {}).isTavan === true);
    const isY  = ((p.tavanInfo || {}).isYakin === true);
    const isK  = (p.katlamis === true) || ((p.katlamaInfo || {}).isKatlamis === true);
    const nts  = Number(p.nextTavanScore || 0);
    const trb  = Number(p.tavanRadarBonus || 0);
    if (isT) {
      rBadge = `<span class="tavan-badge" title="🔥 Bugün TAVAN${trb>0?` · +${trb} bonus`:''}">TAVAN</span>`;
    } else if (isY) {
      rBadge = `<span class="tavan-badge yakin" title="Tavana yakın · +${trb} bonus">YAKIN</span>`;
    } else if (nts >= 40) {
      const sim = (p.nextTavanSimilar || [])[0];
      const tip = sim ? `Adaylık: %${nts} · ${sim.code}'a %${sim.sim} benzer` : `Adaylık: %${nts}`;
      rBadge = `<span class="tavan-badge next" title="${tip}">🎯 ${nts}${trb>0?` <small>+${trb}</small>`:''}</span>`;
    } else if (nts >= 20) {
      rBadge = `<span class="tavan-badge next dim" title="Adaylık: %${nts}">${nts}</span>`;
    } else if (isK) {
      const ki = p.katlamaInfo || {};
      rBadge = `<span class="tavan-badge kat" title="Katlamış: ${ki.kat}x (${ki.windowDays}G)">${ki.level || '2X'}</span>`;
    }

    let rowCls = '';
    if (isT) rowCls = 'row-tavan';
    else if (nts >= 55 && _picksFilter === 'tavan') rowCls = 'row-tavan';
    else if (isK && _picksFilter === 'katlama') rowCls = 'row-katlama';
    else if (bedBonus > 0 && _picksFilter === 'bedelsiz') rowCls = 'row-bedelsiz';
    else if (tipe && (Number(tipe.pos52wk) || 999) < 20) rowCls = 'row-tipe';
    else if (xb > 0) rowCls = 'row-sibling';
    else if (sb >= 50) rowCls = 'row-sleeper';
    else if (eb >= 10) rowCls = 'row-early';
    else if (ifyat > 0 && ifk !== null && ifk <= 0) rowCls = 'row-ipo';
    return `
      <tr class="pick-row ${rowCls}" onclick="openStockModal('${p.code}', _picksMap['${p.code}'])">
        <td>${i + 1}</td>
        <td><b class="neon-cy">${p.code}</b></td>
        <td>${Math.round(p.score || 0)}</td>
        <td>${sBadge}</td>
        <td>${eBadge}</td>
        <td>${xBadge}</td>
        <td>${tBadge}</td>
        <td>${iBadge}</td>
        <td>${rBadge}</td>
        <td>${bBadge}</td>
        <td><span class="${aiClass(p.autoThinkDecision)}">${p.autoThinkDecision || '—'}</span> <small>%${p.autoThinkConf || 0}</small></td>
        <td>${(p.guncel || 0).toFixed(2)}₺</td>
        <td class="hedef-col">${_renderKatlamaHedefleri(p)}</td>
        <td>${(p.stop || 0).toFixed(2)}₺</td>
        <td>${(p.rr || 0).toFixed(2)}</td>
        <td>${(p.rsi || 0).toFixed(0)}</td>
        <td><small>${p.sektor || '—'}</small></td>
      </tr>`;
  }).join('');
}

function _updateFilterCounts() {
  const cAll = _picksAll.length;
  const cSlp = _picksAll.filter(p => (p.sleeperBonus || 0) >= 50).length;
  const cEar = _picksAll.filter(p => (p.earlyCatchBonus || 0) >= 10).length;
  const cSib = _picksAll.filter(p => (p.siblingBonus || 0) > 0).length;
  const cTip = _picksAll.filter(p => _kapTipeMap[p.code] != null).length;
  const cBuy = _picksAll.filter(p => {
    const d = (p.autoThinkDecision || '').toUpperCase();
    return d === 'AL' || d === 'GÜÇLÜ AL' || d === 'GUCLU AL';
  }).length;
  const cIpo = _picksAll.filter(p => !!p.ipoAltinda && (p.ipoFiyat || 0) > 0).length;
  const cTav = _picksAll.filter(p => _matchFilter(p, 'tavan')).length;
  const cKat = _picksAll.filter(p => _matchFilter(p, 'katlama')).length;
  const cBed = _picksAll.filter(p => _matchFilter(p, 'bedelsiz')).length;
  const ca = $('cnt-all'), cs = $('cnt-sleeper'), ce = $('cnt-early'),
        cx = $('cnt-sibling'), ct = $('cnt-tipe'), cb = $('cnt-buy'),
        ci = $('cnt-ipo'), cv = $('cnt-tavan'), ck = $('cnt-katlama'),
        cbed = $('cnt-bedelsiz');
  if (ca) ca.textContent = cAll;
  if (cs) cs.textContent = cSlp;
  if (ce) ce.textContent = cEar;
  if (cx) cx.textContent = cSib;
  if (ct) ct.textContent = cTip;
  if (cb) cb.textContent = cBuy;
  if (ci) ci.textContent = cIpo;
  if (cv) cv.textContent = cTav;
  if (ck) ck.textContent = cKat;
  if (cbed) cbed.textContent = cBed;
}

function _renderSiblingInfo() {
  const panel = $('sibling-info');
  if (!panel) return;
  const list = _picksAll.filter(p => (p.siblingBonus || 0) > 0);
  if (!list.length) {
    panel.innerHTML = `<span class="muted">👥 Henüz aynı ortaklık yapısına sahip kardeş hisse tespit edilmedi — iki aşamalı tarama (BIST 2-Phase) bunu doldurur.</span>`;
    return;
  }
  // Aynı ortağa sahip grupları kümele
  const byOrtak = {};
  list.forEach(p => {
    const o = p.siblingOrtakAd || 'Bilinmeyen';
    (byOrtak[o] = byOrtak[o] || []).push(p);
  });
  const groups = Object.entries(byOrtak)
    .map(([o, arr]) => `<span class="sib-group"><b>${o}</b>: ${arr.map(p => `${p.code}${p.siblingPdOrani ? ` <small>(${Math.round(p.siblingPdOrani)}x küçük)</small>` : ''}`).join(', ')}</span>`)
    .slice(0, 6).join(' · ');
  const katlama = list.filter(p => p.siblingType === 'katlama').length;
  const kucuk = list.filter(p => p.siblingType === 'kucuk_kardes').length;
  panel.innerHTML = `
    <div class="sib-summary">
      <span><b>${list.length}</b> kardeş hisse</span>
      <span>🔥 <b>${katlama}</b> abi katlamış</span>
      <span>⚡ <b>${kucuk}</b> küçük PD'li</span>
    </div>
    <div class="sib-groups">${groups}</div>`;
}

function _setPicksFilter(f) {
  _picksFilter = f;
  document.querySelectorAll('#picks-filter-bar .filter-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.filter === f);
  });
  // Uyuyan performans paneli yalnız Uyuyan filtresinde göster
  const panel = $('sleeper-perf');
  if (panel) panel.style.display = (f === 'sleeper') ? 'flex' : 'none';
  // Ortak Kardeş özet paneli yalnız Sibling filtresinde göster
  const sibPanel = $('sibling-info');
  if (sibPanel) sibPanel.style.display = (f === 'sibling') ? 'block' : 'none';
  // Bedelsiz / Rüçhan KAP katalizör paneli
  const bedPanel = $('bedelsiz-info');
  if (bedPanel) bedPanel.style.display = (f === 'bedelsiz') ? 'block' : 'none';
  if (f === 'sleeper') _refreshSleeperPerf();
  if (f === 'sibling') _renderSiblingInfo();
  if (f === 'bedelsiz') _renderBedelsizInfo();
  if (f === 'tipe' && Object.keys(_kapTipeMap).length === 0 && typeof refreshKapTipeWatchlist === 'function') {
    refreshKapTipeWatchlist();
  }
  _renderPicksTable();
}

async function _refreshSleeperPerf() {
  const panel = $('sleeper-perf');
  if (!panel) return;
  try {
    const r = await api('sleeper_stats');
    const s = (r && r.stats) || {};
    const h7 = (s.by_horizon && s.by_horizon['7d']) || {};
    const h14 = (s.by_horizon && s.by_horizon['14d']) || {};
    const total = s.total_labeled || 0;
    if (total === 0) {
      panel.innerHTML = `<span class="muted">💤 Henüz Uyuyan Mücevher etiketli sinyal birikmedi — ilk taramalardan sonra burada gerçek getiri raporu çıkacak.</span>`;
      return;
    }
    const cls7 = (h7.avg_ret || 0) >= 0 ? 'pos' : 'neg';
    const cls14 = (h14.avg_ret || 0) >= 0 ? 'pos' : 'neg';
    panel.innerHTML = `
      <div class="stat"><span class="lbl">Etiketli Sinyal</span><span class="val">${total}</span></div>
      <div class="stat"><span class="lbl">7G Olgun</span><span class="val">${h7.n || 0}</span></div>
      <div class="stat"><span class="lbl">7G Kazanma</span><span class="val">${(h7.win_pct || 0).toFixed(1)}%</span></div>
      <div class="stat"><span class="lbl">7G Ort. Getiri</span><span class="val ${cls7}">${(h7.avg_ret || 0).toFixed(2)}%</span></div>
      <div class="stat"><span class="lbl">14G Kazanma</span><span class="val">${(h14.win_pct || 0).toFixed(1)}%</span></div>
      <div class="stat"><span class="lbl">14G Ort. Getiri</span><span class="val ${cls14}">${(h14.avg_ret || 0).toFixed(2)}%</span></div>
      <div class="stat"><span class="lbl">En İyi 7G</span><span class="val pos">${(h7.best || 0).toFixed(1)}%</span></div>
    `;
  } catch (e) {
    panel.innerHTML = `<span class="muted">Performans verisi yüklenemedi: ${e.message}</span>`;
  }
}

function _renderBedelsizInfo() {
  const panel = $('bedelsiz-info');
  if (!panel) return;
  const list = _picksAll.filter(p => (p.kapBedelsizBonus || 0) > 0);
  if (!list.length) {
    panel.innerHTML = `<span class="muted">🎁 Henüz bedelsiz/rüçhan duyurusu tespit edilmedi — tarama tamamlanınca burada görünecek.</span>`;
    return;
  }

  // İki segmente ayır: Bedelsiz Sermaye Artırımı vs Rüçhan Hakkı
  const bedelsizList = [];
  const ruchanList   = [];
  list.forEach(p => {
    const items = p.kapBedelsizItems || [];
    const hasRuchan = items.some(it => String(it[1] || '').toLowerCase().includes('rüçhan'));
    if (hasRuchan) ruchanList.push(p);
    else bedelsizList.push(p);
  });

  function _mkRow(p) {
    const bonus = Number(p.kapBedelsizBonus || 0);
    const score = Math.round(p.score || 0);
    const items = p.kapBedelsizItems || [];
    const desc  = items.length ? String(items[0][1] || '').slice(0, 80) : 'KAP Bedelsiz başvuru';
    return `<tr class="pick-row" onclick="openStockModal('${p.code}', _picksMap['${p.code}'])" style="cursor:pointer;">
      <td><b class="neon-cy">${p.code}</b></td>
      <td><b style="color:#00f3ff;">${score}</b></td>
      <td><span class="neon-grn">+${bonus}</span></td>
      <td>${(p.guncel || 0).toFixed(2)}₺</td>
      <td><span class="${aiClass(p.autoThinkDecision)}">${p.autoThinkDecision || '—'}</span></td>
      <td class="muted small">${desc}</td>
    </tr>`;
  }

  const hdr = `<tr><th>Kod</th><th>Skor</th><th>Bonus</th><th>Fiyat</th><th>AI</th><th>KAP Notu</th></tr>`;

  let html = '<div class="bedelsiz-kap-wrap">';

  if (bedelsizList.length) {
    html += `<div class="bedelsiz-segment">
      <div class="segment-title">🎁 Bedelsiz Sermaye Artırımı <span class="muted small">(${bedelsizList.length} hisse)</span></div>
      <table class="bd-table"><thead>${hdr}</thead><tbody>
        ${bedelsizList.map(_mkRow).join('')}
      </tbody></table>
    </div>`;
  }

  if (ruchanList.length) {
    html += `<div class="bedelsiz-segment ruchan">
      <div class="segment-title">💰 Rüçhan Hakkı Kullanımı <span class="muted small">(${ruchanList.length} hisse)</span></div>
      <table class="bd-table"><thead>${hdr}</thead><tbody>
        ${ruchanList.map(_mkRow).join('')}
      </tbody></table>
    </div>`;
  }

  html += '</div>';
  panel.innerHTML = html;
}

async function refreshPicks() {
  try {
    const data = await api('top_picks');
    $('market-mode').textContent = `Piyasa: ${data.marketMode || '—'}`;
    $('last-scan').textContent = data.updated ? `Son tarama: ${data.updated}` : 'Henüz tarama yok';
    _picksAll = data.picks || [];
    _picksAll.forEach(p => { _picksMap[p.code] = p; });
    _updateFilterCounts();
    _renderPicksTable();
    _renderSiblingInfo();
    if (_picksFilter === 'sleeper') _refreshSleeperPerf();
  } catch (e) { console.error(e); }
}

// Filtre butonlarına tıklamayı bağla — DOM hazırsa hemen, değilse sayfanın altında.
function _wirePicksFilters() {
  const bar = document.getElementById('picks-filter-bar');
  if (!bar) return;
  bar.querySelectorAll('.filter-btn').forEach(b => {
    b.addEventListener('click', () => _setPicksFilter(b.dataset.filter));
  });
}
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _wirePicksFilters);
} else {
  _wirePicksFilters();
}

async function refreshPositions() {
  try {
    await api('oto_prices').catch(() => {});
    const data = await api('oto_status');
    const positions = data.positions || {};
    const codes = Object.keys(positions);
    $('positions-count').textContent = `${codes.length} pozisyon`;
    const body = $('positions-body');
    if (codes.length === 0) {
      body.innerHTML = '<tr><td colspan="7" class="muted">Pozisyon yok — AI fırsat bekliyor</td></tr>';
      return;
    }
    body.innerHTML = codes.map(code => {
      const p = positions[code];
      return `<tr class="pick-row" onclick="openStockModal('${code}', {})" style="cursor:pointer;">
        <td><b class="neon-cy">${code}</b></td>
        <td>${(p.entry || 0).toFixed(2)}₺</td>
        <td>${(p.guncel || 0).toFixed(2)}₺</td>
        <td>${fmtPct(p.pnl_pct)}</td>
        <td>${(p.h1 || 0).toFixed(2)}₺</td>
        <td>${(p.stop || 0).toFixed(2)}₺</td>
        <td><span class="${aiClass(p.ai_decision_live || p.ai_decision)}">${p.ai_decision_live || p.ai_decision || '—'}</span></td>
      </tr>`;
    }).join('');
  } catch (e) { console.error(e); }
}

async function refreshNeural() {
  try {
    const [s, tb] = await Promise.all([
      api('neural_stats').catch(() => ({})),
      api('triple_brain').catch(() => ({}))
    ]);
    const ds = tb.dual_brain_stats || {};
    const champ = (ds.current_champion || 'tie').toLowerCase();
    const totalDuels = ds.total_duels || 0;
    const champEmoji = { alpha: '🥇', beta: '🥈', gamma: '🥉', tie: '🤝' }[champ] || '🤝';

    // Beyin başına özet (ağ ham istatistik + düello kazanım)
    const brains = ['alpha','beta','gamma'].map(k => {
      const n = s[k] || {};
      const wins   = ds[`${k}_wins`]   || 0;
      const streak = ds[`${k}_streak`] || 0;
      const isChamp = champ === k;
      const ready  = (n.trained || 0) >= 20;
      const acc    = (n.accuracy || 0);
      const accCls = acc >= 60 ? 'good' : (acc >= 50 ? 'ok' : (acc > 0 ? 'warn' : 'muted'));
      return `<tr${isChamp ? ' class="champ-row"' : ''}>
        <td><b>${isChamp ? '👑 ' : ''}${k.toUpperCase()}</b></td>
        <td>${(n.trained || 0).toLocaleString('tr-TR')}${ready ? '' : ' <span class="muted small">(hazır değil)</span>'}</td>
        <td class="${accCls}">${acc.toFixed(1)}%</td>
        <td>${wins}</td>
        <td>${streak > 0 ? '🔥'+streak : '—'}</td>
        <td>${(n.avg_loss || 0).toFixed(3)}</td>
      </tr>`;
    }).join('');

    // Delta meta-beyin satırı
    const delt = s.delta || {};
    const deltTrained = delt.trained || 0;
    const deltReady = deltTrained >= 20;
    const deltAcc = delt.accuracy || 0;
    const deltAccCls = deltAcc >= 60 ? 'good' : (deltAcc >= 50 ? 'ok' : (deltAcc > 0 ? 'warn' : 'muted'));
    const deltaRow = `<tr style="border-top:1px solid #333;">
      <td><b>⚡ DELTA</b> <span class="muted small">meta</span></td>
      <td>${deltTrained.toLocaleString('tr-TR')}${deltReady ? '' : ' <span class="muted small">(öğreniyor)</span>'}</td>
      <td class="${deltAccCls}">${deltAcc.toFixed(1)}%</td>
      <td colspan="2"><span class="muted small">stacking ensemble</span></td>
      <td>${(delt.avg_loss || 0).toFixed(3)}</td>
    </tr>`;

    // Düello log (son 5)
    const recent = (ds.duel_log || []).slice(0, 5);
    const duelLog = recent.length === 0
      ? '<p class="muted small">⚡ Hızlı düello aktif — snapshot\'lar 1 gün dolunca otomatik başlar (v39: 7→1 gün, 7x daha hızlı öğrenme).</p>'
      : `<div class="duel-log small">
          <b>Son düellolar:</b>
          ${recent.map(d => {
            const winner = d.loser === 'tie' || d.loser === 'all' ? 'Berabere'
                         : d.loser === 'alpha' ? 'β+γ kazandı'
                         : d.loser === 'beta'  ? 'α+γ kazandı'
                         : d.loser === 'gamma' ? 'α+β kazandı'
                         : d.loser === 'alpha_beta' ? '🥉 Gamma şampiyon'
                         : d.loser === 'alpha_gamma' ? '🥈 Beta şampiyon'
                         : d.loser === 'beta_gamma'  ? '🥇 Alpha şampiyon'
                         : d.loser;
            const retCls = d.ret > 0 ? 'good' : (d.ret < 0 ? 'bad' : '');
            return `<div>${d.at} <b>${d.code}</b> → ${winner} <span class="${retCls}">(${d.ret > 0 ? '+' : ''}${d.ret}%)</span></div>`;
          }).join('')}
        </div>`;

    const ties = ds.ties || 0;
    const tiePct = totalDuels > 0 ? (ties / totalDuels * 100).toFixed(0) : 0;

    $('neural-stats').innerHTML = `
      <div class="champ-banner">
        ${champEmoji} <b>Şampiyon: ${champ.toUpperCase()}</b>
        <span class="muted">· Toplam düello: ${totalDuels}</span>
        ${ties > 0 ? `<span class="muted">· Berabere: ${ties} (%${tiePct})</span>` : ''}
      </div>
      <table class="brain-tbl">
        <tr><th>Beyin</th><th>Eğitilmiş</th><th>Doğruluk</th><th>Düello Kazanımı</th><th>Streak</th><th>Loss</th></tr>
        ${brains}
        ${deltaRow}
      </table>
      ${duelLog}
      <p class="muted small">Snapshot: ${s.snapshots || 0} • Takip: ${s.stocks_tracked || 0} hisse • Genel tahmin doğruluğu: %${(s.prediction_accuracy?.oran || 0)}</p>
    `;
  } catch (e) { $('neural-stats').textContent = 'Hata: ' + e.message; }
}

async function refreshLog() {
  try {
    const r = await api('oto_log');
    const logs = r.log || [];
    if (logs.length === 0) { $('oto-log').innerHTML = '<li>Boş</li>'; return; }
    $('oto-log').innerHTML = logs.slice(0, 40).map(l => {
      const t = l.time || l.tarih || l.date || '';
      const src = l.source === 'daemon' ? '<span class="muted small">[daemon]</span> '
                : l.source === 'oto'    ? '<span class="muted small">[oto]</span> '
                : '';
      return `<li class="t-${l.type || 'info'}">${src}<b>${t}</b> ${l.msg || ''}</li>`;
    }).join('');
  } catch (e) {}
}

async function refreshScanProgress() {
  try {
    const p = await api('scan_progress');
    if (p.status === 'idle') {
      $('scan-bar').style.width = '0%';
      $('scan-status').textContent = '⏸ Beklemede';
    } else if (p.status === 'done') {
      $('scan-bar').style.width = '100%';
      $('scan-status').textContent = '✅ Tamamlandı';
      refreshPicks(); refreshPositions();
    } else if (p.status === 'error') {
      $('scan-status').textContent = '❌ Hata: ' + (p.err || '');
    } else {
      $('scan-bar').style.width = (p.pct || 0) + '%';
      $('scan-status').textContent = `🔄 Taranıyor... %${p.pct || 0}`;
    }
    const s = await api('daemon_status').catch(() => null);
    if (s) {
      const next = s.next_scan_in;
      if (next != null && next > 0) {
        const m = Math.floor(next / 60), sec = next % 60;
        $('next-scan').textContent = `Sonraki otomatik tarama: ${m}d ${sec}sn içinde · ${s.scan_count || 0} tarama tamamlandı`;
      } else {
        $('next-scan').textContent = `${s.scan_count || 0} tarama tamamlandı`;
      }
      $('daemon-status').textContent = s.alive === false ? '⚠ Daemon yok' : '⚡ AI Aktif';
      $('daemon-status').className = s.alive === false ? 'daemon-down' : 'daemon-live';
    }
  } catch (e) {}
}

// ── KAP "Tipe Dönüşüm" Watchlist ──────────────────────────────────────
function _pos52Class(v) {
  const n = Number(v) || 0;
  if (n < 10) return 'pos52-deep';
  if (n < 25) return 'pos52-low';
  if (n < 50) return 'pos52-mid';
  return 'pos52-high';
}
function _ageClass(d) {
  const n = Number(d) || 0;
  if (n <= 7)  return 'age-fresh';
  if (n <= 21) return 'age-recent';
  return 'age-old';
}
function _escapeHtml(s) {
  return String(s || '').replace(/[&<>"']/g, c => (
    { '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[c]));
}

async function refreshKapTipeWatchlist(force) {
  const tbl   = $('kap-tipe-table');
  const body  = $('kap-tipe-body');
  const empty = $('kap-tipe-empty');
  const meta  = $('kap-tipe-meta');
  if (!tbl || !body) return;
  try {
    const params = { days: 364 };  // 52 hafta
    if (force) params.refresh = 1;
    const data = await api('kap_tipe_watchlist', params);
    const items = data.items || [];
    if (meta) {
      const ageMin = Math.floor((data.ageSec || 0) / 60);
      const src = data.fromCache ? `önbellek (${ageMin}dk)` : 'taze';
      meta.textContent = `· ${data.matched || 0}/${data.scanned || 0} hisse · ${src}`;
    }
    // Picks tablosundaki 📜 sütunu/filtre için harita güncelle
    const newMap = {};
    items.forEach(r => { if (r && r.code) newMap[r.code] = r; });
    _kapTipeMap = newMap;
    if (_picksAll.length) {
      _updateFilterCounts();
      _renderPicksTable();
    }
    if (items.length === 0) {
      tbl.style.display = 'none';
      empty.style.display = '';
      return;
    }
    empty.style.display = 'none';
    tbl.style.display = '';
    body.innerHTML = items.map((r, i) => {
      const pos = Number(r.pos52wk || 0);
      const guncel = Number(r.guncel || 0);
      const score  = Number(r.score  || 0);
      const baslik = _escapeHtml(r.baslik || '');
      const kapLink = r.link
        ? `<a class="kap-link" href="${_escapeHtml(r.link)}" target="_blank" rel="noopener" onclick="event.stopPropagation();">${baslik}</a>`
        : baslik;
      return `<tr class="tipe-row" onclick="openStockModal('${r.code}', {})">
        <td class="muted">${i + 1}</td>
        <td><b class="neon-cy">${r.code}</b></td>
        <td class="${_pos52Class(pos)}">%${pos.toFixed(1)}</td>
        <td>${guncel > 0 ? guncel.toFixed(2) + '₺' : '—'}</td>
        <td>${score > 0 ? Math.round(score) : '—'}</td>
        <td class="muted">${_escapeHtml(r.sektor || '—')}</td>
        <td class="${_ageClass(r.ageDays)}">${Math.round(r.ageDays || 0)}g</td>
        <td title="${_escapeHtml(r.tarih || '')}">${kapLink}</td>
      </tr>`;
    }).join('');
  } catch (e) {
    console.error(e);
    if (meta) meta.textContent = '· yüklenemedi: ' + e.message;
  }
}

(function _wireKapTipeRefresh() {
  const btn = document.getElementById('kap-tipe-refresh');
  if (!btn) {
    document.addEventListener('DOMContentLoaded', _wireKapTipeRefresh);
    return;
  }
  btn.addEventListener('click', () => {
    btn.disabled = true;
    btn.textContent = '⏳ Hesaplanıyor...';
    refreshKapTipeWatchlist(true).finally(() => {
      btn.disabled = false;
      btn.textContent = '⟳ Yenile';
    });
  });
})();

// ── 🚀 Tavan & Katlama Radarı ─────────────────────────────────────────
function _tavanLevelTr(lv) {
  return ({ 'ÇOK_YÜKSEK': 'Çok Yüksek', 'YÜKSEK': 'Yüksek',
            'ORTA': 'Orta', 'DÜŞÜK': 'Düşük' })[lv] || lv || '';
}

function _renderTavanReason(r) {
  const w = Number(r.weight || 0);
  const cls = w >= 70 ? 'pos' : (w >= 40 ? '' : 'muted');
  return `<span class="${cls}" title="${(r.value || '').replace(/"/g,'&quot;')}">${r.label || r.key}</span>`;
}

function _renderTavanRow(item, kind) {
  const code = item.code || '';
  const fark = Number(item.fark || 0);
  const tdist = Number(item.tDist || 0);
  const score = Number(item.score || 0);
  const sektor = item.sektor || '';
  const reasons = (item.reasons || item.factors || []).slice(0, 4)
                   .map(_renderTavanReason).join(' ');
  let head = '';
  if (kind === 'tavan') {
    const cls = fark >= 0 ? 'pos' : 'neg';
    head = `<b>${code}</b>
      <span class="stat ${cls}">${fark >= 0 ? '+' : ''}${fark.toFixed(2)}%</span>
      <span class="stat muted">tavana ${tdist.toFixed(2)}%</span>
      <span class="stat">${(item.guncel || 0).toFixed(2)}₺</span>`;
  } else if (kind === 'kat') {
    head = `<b>${code}</b>
      <span class="stat pos">${item.kat ? item.kat.toFixed(2) : '?'}x</span>
      <span class="stat muted">${item.windowDays || 0}G · dip ${(item.fromPrice || 0).toFixed(2)}₺</span>
      <span class="stat">${(item.guncel || 0).toFixed(2)}₺</span>`;
  } else if (kind === 'next') {
    head = `<b>${code}</b>
      <span class="stat pos">🎯 ${score}</span>
      <span class="stat muted">${_tavanLevelTr(item.level)}</span>
      <span class="stat">${fark >= 0 ? '+' : ''}${fark.toFixed(2)}% · tav ${tdist.toFixed(2)}%</span>`;
  }

  let similar = '';
  if (kind === 'next' && (item.similar || []).length) {
    const top3 = item.similar.slice(0, 3).map(s => {
      const t = s.type === 'katlama' ? '💎' : '🔥';
      const ageStr = s.ageDays > 0 ? ` <span class="meta">(${s.ageDays}g önce)</span>` : '';
      const katStr = (s.kat && s.kat > 1.05) ? ` ${s.kat.toFixed(2)}x` : '';
      return `<span><b>${s.code}</b>${katStr} ${t}<small> %${s.sim}</small>${ageStr}</span>`;
    }).join(' · ');
    similar = `<div class="similar">📡 Benzer geçmiş kalıplar: ${top3}</div>`;
  }

  const sek = sektor ? `<div class="meta">${sektor}</div>` : '';
  return `<div class="tavan-row ${kind}" onclick="openStockModal('${code}', _picksMap['${code}'] || {})">
    <div class="head">${head}</div>
    ${reasons ? `<div class="reasons">${reasons}</div>` : ''}
    ${similar}
    ${sek}
  </div>`;
}

async function refreshTavanRadar() {
  const colT = $('tavan-list-tavan');
  const colK = $('tavan-list-kat');
  const colN = $('tavan-list-next');
  const meta = $('tavan-radar-meta');
  if (!colT || !colK || !colN) return;
  try {
    const r = await api('tavan_radar');
    const sumr = r.summary || {};
    if (meta) {
      meta.textContent = `· DNA arşivi: ${sumr.archiveSize || 0} kayıt · Son tarama: ${r.lastScan || '—'}`;
    }
    const cT = $('tavan-cnt-tavan'), cK = $('tavan-cnt-kat'), cN = $('tavan-cnt-next');
    if (cT) cT.textContent = `(${(r.currentlyTavan || []).length})`;
    if (cK) cK.textContent = `(${(r.katlamalar     || []).length})`;
    if (cN) cN.textContent = `(${(r.nextCandidates || []).length})`;

    const tList = (r.currentlyTavan || []);
    colT.innerHTML = tList.length
      ? tList.map(it => _renderTavanRow(it, it.level === 'YAKIN' ? 'yakin' : 'tavan')).join('')
      : `<span class="muted">Bugün tavan vuran/yakın hisse yok — tarama bekleniyor.</span>`;

    const kList = (r.katlamalar || []);
    colK.innerHTML = kList.length
      ? kList.map(it => _renderTavanRow(it, 'kat')).join('')
      : `<span class="muted">Henüz katlamış hisse tespit edilmedi.</span>`;

    const nList = (r.nextCandidates || []);
    colN.innerHTML = nList.length
      ? nList.map(it => _renderTavanRow(it, 'next')).join('')
      : `<span class="muted">Aday yok — DNA arşivi henüz dolmamış olabilir. İlk taramalardan sonra burada AI tahminleri çıkacak.</span>`;
  } catch (e) {
    if (meta) meta.textContent = '· yüklenemedi: ' + e.message;
  }
}

function renderTavan(code, d) {
  if (!d || d.ok === false) {
    return `<div class="muted" style="padding:16px;">Veri yok: ${(d && d.err) || 'bilinmiyor'}</div>`;
  }
  const t = d.tavan || {};
  const k = d.katlama || {};
  const n = d.next  || {};
  const reasons = (d.reasons || []).slice(0, 10);
  const similar = (n.similar || []).slice(0, 5);

  const tavanBlock = `
    <div class="tavan-row ${t.isTavan?'tavan':(t.isYakin?'yakin':'')}">
      <div class="head">
        <b>🚀 Tavan Durumu: ${t.level || 'NORMAL'}</b>
        <span class="stat ${(t.dailyChange||0)>=0?'pos':'neg'}">${(t.dailyChange||0)>=0?'+':''}${(t.dailyChange||0).toFixed(2)}%</span>
        <span class="stat muted">tavana ${(t.distanceToTavan||0).toFixed(2)}%</span>
      </div>
    </div>`;

  const katBlock = `
    <div class="tavan-row ${k.isKatlamis?'kat':''}">
      <div class="head">
        <b>💎 Katlama: ${k.level || 'YOK'}</b>
        <span class="stat pos">${(k.kat||1).toFixed(2)}x</span>
        <span class="stat muted">${k.windowDays || 0} gün penceresinde · dip ${(k.fromPrice||0).toFixed(2)}₺</span>
      </div>
      <div class="reasons">
        <span>1A: ${(k.ret1m||0).toFixed(1)}%</span>
        <span>3A: ${(k.ret3m||0).toFixed(1)}%</span>
        <span>1Y: ${(k.retYil||0).toFixed(1)}%</span>
      </div>
    </div>`;

  const nextBlock = `
    <div class="tavan-row next">
      <div class="head">
        <b>🎯 Sıradaki Tavan Tahmini: ${n.score || 0}/100</b>
        <span class="stat pos">${_tavanLevelTr(n.level)}</span>
        <span class="stat muted">heuristik: ${n.heuristic||0} · pattern: +${n.patternBonus||0}</span>
      </div>
      <div class="meta">DNA arşivi: ${n.archiveSize || 0} kayıttan eşleşme aranıyor</div>
    </div>`;

  const reasonsHtml = reasons.length
    ? `<h4 style="margin:14px 0 6px;">📋 NEDEN faktörleri (önem sırasına göre)</h4>
       <table class="brain-tbl"><tr><th>#</th><th>Faktör</th><th>Açıklama</th><th>Ağırlık</th></tr>
       ${reasons.map((r,i)=>`<tr><td>${i+1}</td><td>${r.label||r.key}</td><td class="muted">${r.value||''}</td><td><b>${r.weight||0}</b></td></tr>`).join('')}
       </table>`
    : '<p class="muted small">NEDEN faktörü bulunamadı.</p>';

  const simHtml = similar.length
    ? `<h4 style="margin:14px 0 6px;">📡 Geçmiş benzer kalıplar (cosine DNA)</h4>
       <table class="brain-tbl"><tr><th>#</th><th>Hisse</th><th>Benzerlik</th><th>Tip</th><th>Çarpan</th><th>O Gün %</th><th>Kaç gün önce</th><th>Sektör</th></tr>
       ${similar.map((s,i)=>{
          const t = s.type === 'katlama' ? '💎 KATLAMA' : '🔥 TAVAN';
          return `<tr><td>${i+1}</td><td><b>${s.code}</b> <small class="muted">${s.name||''}</small></td>
                  <td><b class="pos">%${s.sim}</b></td><td>${t}</td>
                  <td>${(s.kat||1).toFixed(2)}x</td>
                  <td>${(s.fark||0).toFixed(2)}%</td>
                  <td class="muted">${s.ageDays||'?'}g</td>
                  <td class="muted">${s.sektor||'—'}</td></tr>`;
       }).join('')}
       </table>
       <p class="muted small" style="margin-top:6px;">📡 Bu hissenin teknik+temel DNA'sı, geçmişte tavan vuran yukarıdaki hisselerin DNA'sıyla %${similar[0]?.sim||0} oranında örtüşüyor. Pattern ne kadar güçlüyse aday skoru o kadar yüksek olur.</p>`
    : '<p class="muted small">Henüz yeterli geçmiş kalıp yok — DNA arşivi her tarama sonu büyüyor. İlk tavan/katlama vakaları biriktikçe burası dolar.</p>';

  return `
    <div style="padding:6px;">
      <div class="champ-banner" style="margin-bottom:10px;">
        🦅 ${code} <span class="muted">· ${d.sektor || ''} · Aday Bonusu: <b>+${d.bonus||0}</b></span>
      </div>
      ${tavanBlock}
      ${katBlock}
      ${nextBlock}
      ${reasonsHtml}
      ${simHtml}
    </div>`;
}

// Klavye kısayolu: ESC ile modal kapat
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeStockModal(); });

refreshPicks(); refreshPositions(); refreshNeural(); refreshLog(); refreshScanProgress();
refreshKapTipeWatchlist();
refreshTavanRadar();
setInterval(refreshScanProgress, 2000);
setInterval(refreshPositions, 8000);
setInterval(refreshLog, 6000);
setInterval(refreshNeural, 20000);
setInterval(refreshPicks, 30000);
setInterval(refreshKapTipeWatchlist, 5 * 60 * 1000);  // 5 dk
setInterval(refreshTavanRadar, 60 * 1000);  // 1 dk
