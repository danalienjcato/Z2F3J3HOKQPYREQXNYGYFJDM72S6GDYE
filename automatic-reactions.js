(async function () {
  const root = document.getElementById('automatic-reactions');
  if (!root) return;
  // Display convention: 1 gold pip = USD 0.01/oz. Not universal across brokers.
  const PIP_SIZE = 0.01;
  const WINDOW = '30';
  const groups = ['FOMC', 'CPI', 'PPI', 'GDP', 'PCE', 'CLAIMS'];
  function note(item) {
    const title = String(item.title || '');
    if (item.category === 'FOMC') {
      if (/minutes of the federal open market committee/i.test(title)) return 'FOMC minutes released — no new rate decision';
      const decisions = {
        '20261028': 'Rates unchanged — 3.75%–4.00%',
        '20260916': 'Rates increased 0.25 percentage points — 3.75%–4.00%',
        '20260729': 'Rates unchanged — 3.50%–3.75%'
      };
      const match = String(item.url || '').match(/monetary(\d{8})a\.htm/);
      return match && decisions[match[1]] ? decisions[match[1]] : 'FOMC rate decision — details not yet verified';
    }
    if (item.category === 'GDP') return 'US economic growth report';
    if (item.category === 'PCE') return 'Federal Reserve inflation measure';
    if (item.category === 'CLAIMS') return 'Weekly unemployment claims';
    const m = title.match(/(?:increases?|rises?|rose|up|advances?|falls?|fell|declines?|decreases?|drops?)\s+([\d.]+%)/i);
    if (m) return (item.category === 'CPI' ? 'Consumer prices' : 'Producer prices') + ' ' + (/fall|declin|decreas|drop/i.test(m[0]) ? 'fell ' : 'rose ') + m[1];
    return item.category === 'CPI' ? 'Consumer inflation report' : 'Producer inflation report';
  }
  function make(tag, cls, value) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (value !== undefined) el.textContent = value;
    return el;
  }
  async function refresh() {
    try {
      const response = await fetch('./reactions.json?t=' + Date.now(), {cache:'no-store'});
      if (!response.ok) throw new Error('Historical data unavailable');
      const data = await response.json();
      const items = Array.isArray(data.items) ? data.items : [];
      root.replaceChildren();
      const summary = make('p','muted',items.length + ' verified historical reactions. Showing the latest six per announcement type.');
      root.append(summary);
      const explanation = make('p','muted','Gold movement measured 30 minutes after release against the minute before release. Pip display assumes $0.01 per pip on XAUUSD; your broker may define pips differently.');
      root.append(explanation);
      for (const category of groups) {
        const section = make('section','history-group');
        section.append(make('h3','history-heading',category + ' history'));
        const subset = items.filter(x => x.category === category).sort((a,b)=>new Date(b.release_time_utc)-new Date(a.release_time_utc));
        if (!subset.length) section.append(make('p','muted','No verified reactions yet.'));
        for (const item of subset.slice(0,6)) {
          const card = make('article','history-card');
          const date = new Date(item.release_time_utc || item.published);
          card.append(make('div','history-date',date.toLocaleDateString('en-ZA',{timeZone:'Africa/Johannesburg',day:'numeric',month:'short',year:'numeric'})));
          card.append(make('div','history-note',note(item)));
          const move = item.moves && item.moves[WINDOW];
          if (move == null || !Number.isFinite(Number(move))) {
            card.append(make('div','muted','30-minute gold movement unavailable'));
          } else {
            const pips = Math.round(Math.abs(Number(move)) / PIP_SIZE).toLocaleString('en-ZA');
            const direction = Number(move)>0 ? 'rose' : Number(move)<0 ? 'dropped' : 'was unchanged';
            card.append(make('div','history-move '+(Number(move)>0?'good':Number(move)<0?'bad':''),'Gold '+direction+(Number(move)===0?'':' '+pips+' pips')));
          }
          section.append(card);
        }
        if (subset.length>6) {
          const details=make('details','history-older');
          details.append(make('summary','', 'Show '+(subset.length-6)+' older '+category+' reactions'));
          for(const item of subset.slice(6)) {
            const row=make('p','muted');
            const d=new Date(item.release_time_utc || item.published).toLocaleDateString('en-ZA',{timeZone:'Africa/Johannesburg',day:'numeric',month:'short',year:'numeric'});
            const m=item.moves&&item.moves[WINDOW];
            row.textContent=d+' — '+note(item)+' — '+(m==null?'No 30m movement':Number(m)>0?'Gold rose '+Math.round(Math.abs(Number(m))/PIP_SIZE).toLocaleString('en-ZA')+' pips':Number(m)<0?'Gold dropped '+Math.round(Math.abs(Number(m))/PIP_SIZE).toLocaleString('en-ZA')+' pips':'Gold unchanged');
            details.append(row);
          }
          section.append(details);
        }
        root.append(section);
      }
      const footer=make('p','muted','Key notes are simplified descriptions, not verified rate decisions. Price reactions are measured moves, not proof the announcement caused them.');
      root.append(footer);
    } catch(e) {
      root.textContent='Could not load verified historical reactions. Please refresh.';
    }
  }
  await refresh();
  setInterval(refresh,120000);
})();
