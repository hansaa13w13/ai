// ═══════════════════════════════════════════════════════════════════════
//  BIST PREDATOR v35 · Python — TAM OTONOM İZLEME PANELİ
//  Hiçbir manuel kontrol yok. Tüm tarama, al/sat, eğitim AI daemon tarafından
//  otomatik yapılır. Bu script sadece okuma/görüntüleme yapar.
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

async function refreshPicks() {
  try {
    const data = await api('top_picks', { n: 25 });
    $('market-mode').textContent = `Piyasa: ${data.marketMode || '—'}`;
    $('last-scan').textContent = data.updated ? `Son tarama: ${data.updated}` : 'Henüz tarama yok';
    const body = $('picks-body');
    if (!data.picks || data.picks.length === 0) {
      body.innerHTML = '<tr><td colspan="10" class="muted">İlk tarama bekleniyor...</td></tr>';
      return;
    }
    body.innerHTML = data.picks.map((p, i) => `
      <tr>
        <td>${i + 1}</td>
        <td><b>${p.code}</b></td>
        <td>${Math.round(p.score || 0)}</td>
        <td><span class="${aiClass(p.autoThinkDecision)}">${p.autoThinkDecision || '—'}</span> <small>%${p.autoThinkConf || 0}</small></td>
        <td>${(p.guncel || 0).toFixed(2)}₺</td>
        <td>${(p.h1 || 0).toFixed(2)}₺</td>
        <td>${(p.stop || 0).toFixed(2)}₺</td>
        <td>${(p.rr || 0).toFixed(2)}</td>
        <td>${(p.rsi || 0).toFixed(0)}</td>
        <td><small>${p.sektor || '—'}</small></td>
      </tr>
    `).join('');
  } catch (e) { console.error(e); }
}

async function refreshPositions() {
  try {
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
      return `<tr>
        <td><b>${code}</b></td>
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
    const s = await api('neural_stats');
    const html = `
      <table>
        <tr><th>Beyin</th><th>Eğitilmiş</th><th>Doğruluk</th><th>Loss</th><th>Adam</th></tr>
        ${['alpha','beta','gamma'].map(k => {
          const n = s[k] || {};
          return `<tr>
            <td><b>${k.toUpperCase()}</b></td>
            <td>${n.trained || 0}</td>
            <td>${(n.accuracy || 0).toFixed(1)}%</td>
            <td>${(n.avg_loss || 0).toFixed(4)}</td>
            <td>${n.adam_steps || 0}</td>
          </tr>`;
        }).join('')}
      </table>
      <p class="muted small">Snapshot: ${s.snapshots} • Takip: ${s.stocks_tracked} hisse • Tahmin doğruluk: %${(s.prediction_accuracy?.oran || 0)}</p>
    `;
    $('neural-stats').innerHTML = html;
  } catch (e) { $('neural-stats').textContent = 'Hata: ' + e.message; }
}

async function refreshLog() {
  try {
    const r = await api('oto_log');
    const logs = r.log || [];
    if (logs.length === 0) { $('oto-log').innerHTML = '<li>Boş</li>'; return; }
    $('oto-log').innerHTML = logs.slice(0, 30).map(l => {
      const t = l.time || l.tarih || l.date || '';
      return `<li class="t-${l.type || 'info'}"><b>${t}</b> ${l.msg || ''}</li>`;
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

    // Sonraki tarama / daemon durumu
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

// İlk yükleme + sürekli otomatik tazeleme — kullanıcı hiçbir şey tıklamaz
refreshPicks(); refreshPositions(); refreshNeural(); refreshLog(); refreshScanProgress();
setInterval(refreshScanProgress, 2000);
setInterval(refreshPositions, 8000);
setInterval(refreshLog, 6000);
setInterval(refreshNeural, 20000);
setInterval(refreshPicks, 30000);
